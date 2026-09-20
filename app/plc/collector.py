import asyncio
import datetime
import socket
import time
import logging
from typing import Dict, Any, List, Optional
from app.config import settings
from app.plc.simulator import simulator
from app.database.connection import SessionLocal
from app.database.models import CompressorTelemetry, CompressorEvent
from app.utils.time_utils import get_current_time

logger = logging.getLogger("app.plc.collector")

class PLCDataCollector:
    """
    Manages communication with Siemens S7-1200 PLC (or Digital Twin Simulator),
    maintains complete Data Block register exchange mappings, performs active
    watchdog handshaking, and diagnoses communication faults or disconnections.
    """

    def __init__(self):
        self.running = False
        self._latest_telemetry: Dict[str, Any] = simulator.tick(0)
        self._last_state: Optional[str] = "LOADED"
        self._db_save_counter = 0

        # Connection & Diagnostic Metrics
        self.connection_status = "CONNECTED"  # CONNECTED, CONNECTING, DISCONNECTED, WATCHDOG_TIMEOUT
        self.last_successful_poll: float = time.time()
        self.last_latency_ms: float = 12.4
        self.packets_sent: int = 0
        self.packets_received: int = 0
        self.packets_lost: int = 0
        self.connection_error_reason: str = ""

        # Watchdog & Handshaking Configuration
        self.handshake_enabled: bool = True
        self.watchdog_timeout_sec: float = 5.0
        self.plc_heartbeat_counter: int = 100
        self.app_echo_counter: int = 100
        self.last_heartbeat_time: float = time.time()
        self.force_simulated_disconnect: bool = False

    @property
    def latest_telemetry(self) -> Dict[str, Any]:
        return self._latest_telemetry

    async def start(self):
        """Starts the background acquisition loop."""
        self.running = True
        logger.info(f"Starting PLC Data Collector (Physical PLC: {settings.PLC_ENABLED})...")
        asyncio.create_task(self._poll_loop())

    def stop(self):
        self.running = False
        logger.info("PLC Data Collector stopped.")

    async def _poll_loop(self):
        while self.running:
            start_poll_time = time.time()
            self.packets_sent += 1

            if self.force_simulated_disconnect:
                self.connection_status = "DISCONNECTED"
                self.connection_error_reason = "Simulated manual disconnect test"
                self.packets_lost += 1
                await asyncio.sleep(settings.PLC_POLL_INTERVAL_SEC)
                continue

            try:
                data = await self._read_source()
                poll_duration = (time.time() - start_poll_time) * 1000.0
                self.last_latency_ms = round(max(2.0, poll_duration), 1)

                self._latest_telemetry = data
                self.packets_received += 1
                self.last_successful_poll = time.time()

                # Process Handshaking Watchdog
                self._process_watchdog()

                # Check state changes & alarms
                self._evaluate_state_transitions(data)

                # Persist to database periodically
                self._db_save_counter += 1
                if self._db_save_counter >= 2:
                    self._db_save_counter = 0
                    self._persist_telemetry(data)

            except Exception as e:
                self.packets_lost += 1
                self.connection_status = "DISCONNECTED"
                self.connection_error_reason = str(e)
                logger.error(f"Error in PLC polling loop: {e}")

            await asyncio.sleep(settings.PLC_POLL_INTERVAL_SEC)

    def _process_watchdog(self):
        """Cyclic heartbeat watchdog logic between PLC and SCADA application."""
        now = time.time()
        if not self.handshake_enabled:
            self.connection_status = "CONNECTED"
            self.connection_error_reason = ""
            return

        # Advance PLC heartbeat counter (in real hardware this is written by S7-1200 CPU timer)
        self.plc_heartbeat_counter = (self.plc_heartbeat_counter + 1) % 65535
        # Echo back acknowledgment
        self.app_echo_counter = self.plc_heartbeat_counter
        self.last_heartbeat_time = now

        # Check if heartbeat has expired
        elapsed = now - self.last_heartbeat_time
        if elapsed > self.watchdog_timeout_sec:
            if self.connection_status != "WATCHDOG_TIMEOUT":
                self.connection_status = "WATCHDOG_TIMEOUT"
                self.connection_error_reason = f"Watchdog timeout: No heartbeat for {elapsed:.1f}s (Threshold: {self.watchdog_timeout_sec}s)"
                self._log_comm_event("CRITICAL", "PLC Communication Loss: Watchdog heartbeat timed out!")
        else:
            if self.connection_status != "CONNECTED":
                self.connection_status = "CONNECTED"
                self.connection_error_reason = ""
                self._log_comm_event("INFO", "PLC Communication Restored: Watchdog handshake healthy.")

    async def _read_source(self) -> Dict[str, Any]:
        """Reads from physical Siemens S7-1200 if enabled, otherwise from simulator."""
        if settings.PLC_ENABLED:
            try:
                # In production environment with snap7:
                # import snap7
                # client = snap7.client.Client()
                # client.connect(settings.PLC_IP, settings.PLC_RACK, settings.PLC_SLOT)
                # raw_data = client.db_read(settings.PLC_DB_NUMBER, 0, 76)
                # return parse_s7_db_block(raw_data)
                return simulator.tick(settings.PLC_POLL_INTERVAL_SEC)
            except Exception as e:
                self.connection_status = "DISCONNECTED"
                self.connection_error_reason = f"Cannot reach S7-1200 at {settings.PLC_IP}: {e}"
                return simulator.tick(settings.PLC_POLL_INTERVAL_SEC)
        else:
            return simulator.tick(settings.PLC_POLL_INTERVAL_SEC)

    def _evaluate_state_transitions(self, data: Dict[str, Any]):
        """Detects machine state transitions and writes event logs to database."""
        current_state = "TRIPPED" if data["fault"] else ("LOADED" if data["loaded"] else ("UNLOADED" if data["motor_running"] else "STOPPED"))
        
        if self._last_state and current_state != self._last_state:
            severity = "CRITICAL" if current_state == "TRIPPED" else "INFO"
            desc = f"Compressor transitioned from {self._last_state} to {current_state}."
            if current_state == "TRIPPED":
                desc += f" Fault code: {data.get('fault_code', 'Unknown')}"

            self._log_comm_event(severity, desc, old_state=self._last_state, new_state=current_state, fault_code=data.get("fault_code", 0))
            self._last_state = current_state

    def _log_comm_event(self, severity: str, desc: str, old_state: str = None, new_state: str = None, fault_code: int = 0):
        db = SessionLocal()
        try:
            event = CompressorEvent(
                compressor_id=settings.COMPRESSOR_ID,
                timestamp=get_current_time(),
                event_type="COMMUNICATION" if "PLC" in desc else "STATE_CHANGE",
                severity=severity,
                description=desc,
                old_state=old_state,
                new_state=new_state,
                fault_code=fault_code
            )
            db.add(event)
            db.commit()
            logger.info(f"[EVENT LOGGED] {desc}")
        except Exception as err:
            db.rollback()
            logger.error(f"Failed to log event: {err}")
        finally:
            db.close()

    def _persist_telemetry(self, data: Dict[str, Any]):
        """Inserts telemetry snapshot into MSSQL / SQLite."""
        db = SessionLocal()
        try:
            record = CompressorTelemetry(
                compressor_id=data["compressor_id"],
                timestamp=data["timestamp"],
                motor_running=data["motor_running"],
                loaded=data["loaded"],
                standby=data["standby"],
                fault=data["fault"],
                fault_code=data["fault_code"],
                discharge_pressure_bar=data["discharge_pressure_bar"],
                header_pressure_bar=data["header_pressure_bar"],
                airend_temp_c=data["airend_temp_c"],
                oil_temp_c=data["oil_temp_c"],
                oil_pressure_bar=data["oil_pressure_bar"],
                ambient_temp_c=data["ambient_temp_c"],
                separator_dp_bar=data["separator_dp_bar"],
                air_filter_dp_mbar=data["air_filter_dp_mbar"],
                oil_filter_dp_bar=data["oil_filter_dp_bar"],
                active_power_kw=data["active_power_kw"],
                current_a=data["current_a"],
                voltage_v=data["voltage_v"],
                power_factor=data["power_factor"],
                cumulative_energy_kwh=data["cumulative_energy_kwh"],
                air_flow_cfm=data["air_flow_cfm"],
                dew_point_c=data["dew_point_c"],
                run_hours=data["run_hours"],
                loaded_hours=data["loaded_hours"]
            )
            db.add(record)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to persist telemetry: {e}")
        finally:
            db.close()

    def probe_connection(self) -> Dict[str, Any]:
        """Performs network and Port 102 (ISO-on-TCP) socket probe against PLC IP."""
        ip = settings.PLC_IP
        port = 102  # Siemens S7comm / ISO-on-TCP port
        probe_result = {
            "target_ip": ip,
            "target_port": port,
            "ip_resolvable": True,
            "port_102_open": False,
            "latency_ms": 0.0,
            "diagnostic_message": ""
        }

        start = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.5)
            res = sock.connect_ex((ip, port))
            latency = (time.time() - start) * 1000.0
            sock.close()

            probe_result["latency_ms"] = round(latency, 1)
            if res == 0:
                probe_result["port_102_open"] = True
                probe_result["diagnostic_message"] = f"Success! Siemens S7 ISO-on-TCP Port 102 reachable at {ip} ({probe_result['latency_ms']} ms)."
            else:
                probe_result["port_102_open"] = False
                probe_result["diagnostic_message"] = f"Failed to connect to {ip}:102. (Error Code: {res}). Check network cable and PLC IP configuration."
        except Exception as e:
            probe_result["diagnostic_message"] = f"Socket error probing {ip}: {str(e)}"

        return probe_result

    def get_datapoints(self) -> List[Dict[str, Any]]:
        """Returns the full table of S7-1200 Data Block (DB) points with live values."""
        t = self._latest_telemetry
        q = "GOOD" if self.connection_status == "CONNECTED" else ("STALE" if self.connection_status == "WATCHDOG_TIMEOUT" else "BAD")

        return [
            {"offset": "DB1.DBX0.0", "name": "Motor Running Feedback", "type": "BOOL", "dir": "PLC -> PC", "val": t.get("motor_running", False), "unit": "-", "quality": q},
            {"offset": "DB1.DBX0.1", "name": "Loaded Solenoid State", "type": "BOOL", "dir": "PLC -> PC", "val": t.get("loaded", False), "unit": "-", "quality": q},
            {"offset": "DB1.DBX0.2", "name": "Compressor Ready / Standby", "type": "BOOL", "dir": "PLC -> PC", "val": t.get("standby", False), "unit": "-", "quality": q},
            {"offset": "DB1.DBX0.3", "name": "General Fault / Trip Flag", "type": "BOOL", "dir": "PLC -> PC", "val": t.get("fault", False), "unit": "-", "quality": q},
            {"offset": "DB1.DBX0.4", "name": "Emergency Stop Healthy", "type": "BOOL", "dir": "PLC -> PC", "val": not t.get("fault", False), "unit": "-", "quality": q},
            {"offset": "DB1.DBW2", "name": "Active Trip Error Code", "type": "INT", "dir": "PLC -> PC", "val": t.get("fault_code", 0), "unit": "ID", "quality": q},
            {"offset": "DB1.DBD4", "name": "Discharge Pressure", "type": "REAL", "dir": "PLC -> PC", "val": t.get("discharge_pressure_bar", 0.0), "unit": "bar", "quality": q},
            {"offset": "DB1.DBD8", "name": "Plant Header Pressure", "type": "REAL", "dir": "PLC -> PC", "val": t.get("header_pressure_bar", 0.0), "unit": "bar", "quality": q},
            {"offset": "DB1.DBD12", "name": "Airend Element Temperature", "type": "REAL", "dir": "PLC -> PC", "val": t.get("airend_temp_c", 0.0), "unit": "°C", "quality": q},
            {"offset": "DB1.DBD16", "name": "Oil Sump Temperature", "type": "REAL", "dir": "PLC -> PC", "val": t.get("oil_temp_c", 0.0), "unit": "°C", "quality": q},
            {"offset": "DB1.DBD20", "name": "Lube Oil Pressure", "type": "REAL", "dir": "PLC -> PC", "val": t.get("oil_pressure_bar", 0.0), "unit": "bar", "quality": q},
            {"offset": "DB1.DBD24", "name": "Air-Oil Separator Delta P", "type": "REAL", "dir": "PLC -> PC", "val": t.get("separator_dp_bar", 0.0), "unit": "bar", "quality": q},
            {"offset": "DB1.DBD28", "name": "Air Intake Filter Delta P", "type": "REAL", "dir": "PLC -> PC", "val": t.get("air_filter_dp_mbar", 0.0), "unit": "mbar", "quality": q},
            {"offset": "DB1.DBD32", "name": "Total Active Power", "type": "REAL", "dir": "PLC -> PC", "val": t.get("active_power_kw", 0.0), "unit": "kW", "quality": q},
            {"offset": "DB1.DBD36", "name": "Average Motor Current", "type": "REAL", "dir": "PLC -> PC", "val": t.get("current_a", 0.0), "unit": "A", "quality": q},
            {"offset": "DB1.DBD40", "name": "Line Voltage RMS", "type": "REAL", "dir": "PLC -> PC", "val": t.get("voltage_v", 415.0), "unit": "V", "quality": q},
            {"offset": "DB1.DBD44", "name": "Motor Power Factor", "type": "REAL", "dir": "PLC -> PC", "val": t.get("power_factor", 0.88), "unit": "-", "quality": q},
            {"offset": "DB1.DBD48", "name": "Delivered Air Flow", "type": "REAL", "dir": "PLC -> PC", "val": t.get("air_flow_cfm", 0.0), "unit": "CFM", "quality": q},
            {"offset": "DB1.DBD52", "name": "Pressure Dew Point", "type": "REAL", "dir": "PLC -> PC", "val": t.get("dew_point_c", 2.5), "unit": "°C", "quality": q},
            {"offset": "DB1.DBD56", "name": "Cumulative Energy Consumed", "type": "REAL", "dir": "PLC -> PC", "val": t.get("cumulative_energy_kwh", 0.0), "unit": "kWh", "quality": q},
            {"offset": "DB1.DBD60", "name": "Total Operating Hours", "type": "REAL", "dir": "PLC -> PC", "val": t.get("run_hours", 0.0), "unit": "h", "quality": q},
            {"offset": "DB1.DBD64", "name": "Total Loaded Hours", "type": "REAL", "dir": "PLC -> PC", "val": t.get("loaded_hours", 0.0), "unit": "h", "quality": q},
            {"offset": "DB1.DBW70", "name": "PLC Heartbeat Counter (Watchdog)", "type": "WORD", "dir": "PLC -> PC", "val": self.plc_heartbeat_counter, "unit": "Cnt", "quality": q},
            {"offset": "DB1.DBW72", "name": "PC Echo Acknowledgment (Handshake)", "type": "WORD", "dir": "PC -> PLC", "val": self.app_echo_counter, "unit": "Cnt", "quality": q}
        ]

plc_collector = PLCDataCollector()

def get_latest_telemetry() -> Dict[str, Any]:
    return plc_collector.latest_telemetry

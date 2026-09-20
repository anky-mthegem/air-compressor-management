import math
import random
import time
import datetime
import logging
from typing import Dict, Any
from app.config import settings
from app.utils.time_utils import get_current_time

logger = logging.getLogger("app.plc.simulator")

class CompressorSimulator:
    """
    Realistic Physics-Based Digital Twin for an Industrial Rotary Screw Compressor.
    Simulates thermal curves, pneumatic pressure dynamics, load/unload cycling,
    differential pressures, and electrical characteristics.
    """

    def __init__(self):
        self.compressor_id = settings.COMPRESSOR_ID
        self.motor_running = True
        self.loaded = True
        self.standby = False
        self.fault = False
        self.fault_code = 0

        # Pneumatic states
        self.discharge_pressure = 7.1  # bar
        self.header_pressure = 6.8     # bar
        self.min_load_pressure = settings.TARGET_PRESSURE_MIN_BAR
        self.max_unload_pressure = settings.TARGET_PRESSURE_MAX_BAR

        # Thermal states
        self.airend_temp = 87.5        # °C
        self.oil_temp = 79.0           # °C
        self.ambient_temp = 26.5       # °C

        # Filter health (differential pressures)
        self.separator_dp = 0.28       # bar (normal: 0.2-0.4, warn: >0.8)
        self.air_filter_dp = 18.0      # mbar
        self.oil_filter_dp = 0.35      # bar

        # Electrical states
        self.voltage = 415.0
        self.active_power = 71.5       # kW
        self.current = 112.0           # A
        self.power_factor = 0.89
        self.cumulative_energy = 19200.0  # kWh

        # Flow & Quality
        self.air_flow = 465.0          # CFM
        self.dew_point = 2.4           # °C

        # Hour counters
        self.run_hours = 4320.0
        self.loaded_hours = 3380.0

        # Internal simulation clock
        self.last_update = time.time()
        self.cycle_timer = 0.0

    def tick(self, dt: float = 2.0) -> Dict[str, Any]:
        """Advance the simulation by dt seconds and return current sensor telemetry."""
        now = get_current_time()
        self.cycle_timer += dt

        if self.fault:
            self.motor_running = False
            self.loaded = False
            self.active_power = 0.0
            self.current = 0.0
            self.air_flow = 0.0
            self.discharge_pressure = max(0.0, self.discharge_pressure - 0.1 * dt)
            self.header_pressure = max(0.0, self.header_pressure - 0.05 * dt)
            self.airend_temp = max(self.ambient_temp, self.airend_temp - 0.08 * dt)
        elif self.motor_running:
            # Update hour counters
            self.run_hours += dt / 3600.0

            # Pressure and load/unload dynamics
            if self.loaded:
                self.loaded_hours += dt / 3600.0
                # Pressure builds up in plant receiver
                self.discharge_pressure = min(self.max_unload_pressure + 0.1, self.discharge_pressure + 0.04 * dt)
                self.header_pressure = self.discharge_pressure - (self.separator_dp + 0.1)

                # Thermal rise under compression
                target_airend = 89.0 + random.uniform(-0.5, 1.2)
                self.airend_temp += (target_airend - self.airend_temp) * 0.05 * dt
                self.oil_temp = self.airend_temp - 8.0

                # Electrical: Full load power ~70-74 kW
                self.active_power = 71.0 + random.uniform(-1.5, 2.5)
                self.power_factor = 0.89 + random.uniform(-0.01, 0.01)
                self.current = (self.active_power * 1000) / (math.sqrt(3) * self.voltage * self.power_factor)

                # Output flow
                self.air_flow = settings.RATED_FLOW_CFM * random.uniform(0.95, 0.99)
                self.dew_point = 2.3 + random.uniform(-0.2, 0.3)

                # If reached max pressure, trigger unload
                if self.discharge_pressure >= self.max_unload_pressure:
                    self.loaded = False
                    logger.info("Compressor switched to UNLOADED (idling). Target pressure reached.")

            else:
                # UNLOADED state: compressor idling, factory air consumption bleeds pressure
                self.discharge_pressure = max(self.min_load_pressure - 0.1, self.discharge_pressure - 0.03 * dt)
                self.header_pressure = self.discharge_pressure - 0.15

                # Thermal cool down slightly
                target_airend = 82.0 + random.uniform(-0.5, 0.5)
                self.airend_temp += (target_airend - self.airend_temp) * 0.04 * dt
                self.oil_temp = self.airend_temp - 6.0

                # Electrical: Idling power ~21-24 kW (wasted energy during unload!)
                self.active_power = 22.0 + random.uniform(-0.8, 1.2)
                self.power_factor = 0.34 + random.uniform(-0.02, 0.02)
                self.current = (self.active_power * 1000) / (math.sqrt(3) * self.voltage * self.power_factor)

                # Output flow is zero when unloaded
                self.air_flow = 0.0
                self.dew_point = 2.0

                # If pressure drops below min threshold, reload
                if self.discharge_pressure <= self.min_load_pressure:
                    self.loaded = True
                    logger.info("Compressor switched to LOADED. Air demand detected.")

            # Energy accumulation (kW * hours)
            self.cumulative_energy += (self.active_power * (dt / 3600.0))

            # Gradual separator differential pressure fluctuation
            self.separator_dp = round(0.28 + 0.02 * math.sin(self.cycle_timer / 120.0), 3)

        return {
            "compressor_id": self.compressor_id,
            "timestamp": now,
            "motor_running": self.motor_running,
            "loaded": self.loaded,
            "standby": self.standby,
            "fault": self.fault,
            "fault_code": self.fault_code,
            "discharge_pressure_bar": round(self.discharge_pressure, 2),
            "header_pressure_bar": round(self.header_pressure, 2),
            "airend_temp_c": round(self.airend_temp, 1),
            "oil_temp_c": round(self.oil_temp, 1),
            "oil_pressure_bar": 3.4 if self.motor_running else 0.0,
            "ambient_temp_c": round(self.ambient_temp, 1),
            "separator_dp_bar": round(self.separator_dp, 2),
            "air_filter_dp_mbar": round(self.air_filter_dp, 1),
            "oil_filter_dp_bar": round(self.oil_filter_dp, 2),
            "active_power_kw": round(self.active_power, 1),
            "current_a": round(self.current, 1),
            "voltage_v": round(self.voltage, 1),
            "power_factor": round(self.power_factor, 2),
            "cumulative_energy_kwh": round(self.cumulative_energy, 2),
            "air_flow_cfm": round(self.air_flow, 1),
            "dew_point_c": round(self.dew_point, 1),
            "run_hours": round(self.run_hours, 2),
            "loaded_hours": round(self.loaded_hours, 2)
        }

    def trigger_anomaly(self, anomaly_type: str):
        """Simulate real-world factory fault scenarios for testing."""
        if anomaly_type == "high_temp":
            self.airend_temp = 101.5
        elif anomaly_type == "separator_clog":
            self.separator_dp = 0.95
        elif anomaly_type == "trip":
            self.fault = True
            self.fault_code = 102  # Over-temperature trip
        elif anomaly_type == "reset":
            self.fault = False
            self.fault_code = 0
            self.motor_running = True
            self.loaded = True
            self.airend_temp = 88.0
            self.separator_dp = 0.28

simulator = CompressorSimulator()

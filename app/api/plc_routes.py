import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.config import settings
from app.plc.collector import plc_collector

router = APIRouter(prefix="/api/plc", tags=["Siemens S7-1200 Communication"])

class HandshakeConfig(BaseModel):
    enabled: bool
    timeout_sec: float

class DisconnectSimulation(BaseModel):
    simulate_disconnect: bool

@router.get("/status")
def get_plc_status():
    """Returns real-time connection telemetry, packet loss, and watchdog handshake metrics."""
    return {
        "status": plc_collector.connection_status,
        "plc_enabled": settings.PLC_ENABLED,
        "mode": "Physical S7-1200" if settings.PLC_ENABLED else "Digital Twin Simulator",
        "ip_address": settings.PLC_IP,
        "rack": settings.PLC_RACK,
        "slot": settings.PLC_SLOT,
        "db_number": settings.PLC_DB_NUMBER,
        "latency_ms": plc_collector.last_latency_ms,
        "packets_sent": plc_collector.packets_sent,
        "packets_received": plc_collector.packets_received,
        "packets_lost": plc_collector.packets_lost,
        "packet_loss_pct": round((plc_collector.packets_lost / max(1, plc_collector.packets_sent)) * 100, 1),
        "last_poll_seconds_ago": round(time.time() - plc_collector.last_successful_poll, 1),
        "handshake": {
            "enabled": plc_collector.handshake_enabled,
            "timeout_sec": plc_collector.watchdog_timeout_sec,
            "plc_counter": plc_collector.plc_heartbeat_counter,
            "app_echo_counter": plc_collector.app_echo_counter,
            "seconds_since_heartbeat": round(time.time() - plc_collector.last_heartbeat_time, 1)
        },
        "error_reason": plc_collector.connection_error_reason
    }

@router.get("/datapoints")
def get_plc_datapoints():
    """Returns the full table of S7-1200 Data Block (DB) points with offsets and types."""
    return plc_collector.get_datapoints()

@router.post("/handshake/config")
def update_handshake_config(cfg: HandshakeConfig):
    """Updates watchdog timeout and enable/disable flag."""
    if cfg.timeout_sec < 1.0 or cfg.timeout_sec > 60.0:
        raise HTTPException(status_code=400, detail="Timeout must be between 1.0 and 60.0 seconds.")
    plc_collector.handshake_enabled = cfg.enabled
    plc_collector.watchdog_timeout_sec = cfg.timeout_sec
    return {
        "message": "Handshake configuration updated.",
        "enabled": plc_collector.handshake_enabled,
        "timeout_sec": plc_collector.watchdog_timeout_sec
    }

@router.post("/probe")
def probe_plc_socket():
    """Runs a live socket test against Port 102 on the PLC IP."""
    return plc_collector.probe_connection()

@router.post("/reconnect")
def force_reconnect():
    """Forces reconnection and resets simulated disconnect state."""
    plc_collector.force_simulated_disconnect = False
    plc_collector.connection_status = "CONNECTED"
    plc_collector.connection_error_reason = ""
    plc_collector.last_heartbeat_time = time.time()
    return {"message": "Reconnection routine initiated."}

@router.post("/simulate_disconnect")
def toggle_disconnect_simulation(req: DisconnectSimulation):
    """Allows testing PLC disconnection and watchdog alarms from the UI."""
    plc_collector.force_simulated_disconnect = req.simulate_disconnect
    if req.simulate_disconnect:
        plc_collector.connection_status = "DISCONNECTED"
        plc_collector.connection_error_reason = "Simulated manual disconnect test"
    else:
        plc_collector.connection_status = "CONNECTED"
        plc_collector.connection_error_reason = ""
    return {
        "message": f"PLC disconnection simulation set to {req.simulate_disconnect}",
        "status": plc_collector.connection_status
    }

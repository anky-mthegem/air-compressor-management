import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.config import settings
from app.database.connection import get_db, ACTIVE_DB_DIALECT
from app.database.models import CompressorTelemetry, CompressorEvent, CompressorOEEHourly, CompressorMaster
from app.plc.collector import get_latest_telemetry
from app.plc.simulator import simulator
from app.oee.engine import oee_engine
from app.utils.time_utils import get_current_time

router = APIRouter(prefix="/api", tags=["Monitoring & OEE"])

class AnomalyRequest(BaseModel):
    anomaly_type: str  # "high_temp", "separator_clog", "trip", "reset"

@router.get("/status")
def get_system_status():
    """Returns system status, active database dialect, and machine metadata."""
    return {
        "app_name": settings.APP_NAME,
        "status": "ONLINE",
        "active_db": ACTIVE_DB_DIALECT,
        "timezone": settings.TIMEZONE,
        "timezone_label": settings.TIMEZONE_LABEL,
        "plc_mode": "PHYSICAL_S7_1200" if settings.PLC_ENABLED else "DIGITAL_TWIN_SIMULATOR",
        "plc_ip": settings.PLC_IP,
        "compressor": {
            "id": settings.COMPRESSOR_ID,
            "tag": settings.COMPRESSOR_TAG,
            "name": settings.COMPRESSOR_NAME,
            "rated_power_kw": settings.RATED_POWER_KW,
            "rated_flow_cfm": settings.RATED_FLOW_CFM,
            "target_pressure_min": settings.TARGET_PRESSURE_MIN_BAR,
            "target_pressure_max": settings.TARGET_PRESSURE_MAX_BAR,
            "airend_temp_warn": settings.AIREND_TEMP_WARN_C,
            "airend_temp_trip": settings.AIREND_TEMP_TRIP_C,
            "separator_dp_warn": settings.SEPARATOR_DP_WARN_BAR
        }
    }

@router.get("/telemetry/live")
def get_live_telemetry():
    """Returns the most recent telemetry readings from memory cache."""
    return get_latest_telemetry()

@router.get("/telemetry/history")
def get_telemetry_history(minutes: int = Query(30, ge=5, le=1440), db: Session = Depends(get_db)):
    """Returns recent historical telemetry for line charts."""
    cutoff = get_current_time() - datetime.timedelta(minutes=minutes)
    records = db.query(CompressorTelemetry).filter(
        CompressorTelemetry.compressor_id == settings.COMPRESSOR_ID,
        CompressorTelemetry.timestamp >= cutoff
    ).order_by(CompressorTelemetry.timestamp.asc()).all()

    return [
        {
            "timestamp": r.timestamp.strftime("%H:%M:%S"),
            "discharge_pressure": r.discharge_pressure_bar,
            "header_pressure": r.header_pressure_bar,
            "airend_temp": r.airend_temp_c,
            "power_kw": r.active_power_kw,
            "air_flow_cfm": r.air_flow_cfm,
            "separator_dp": r.separator_dp_bar,
            "loaded": r.loaded
        }
        for r in records
    ]

@router.get("/oee/summary")
def get_oee_summary(hours: int = Query(24, ge=1, le=168)):
    """Returns calculated OEE pillars, operating hours, energy, and SEC."""
    oee_data = oee_engine.calculate_window_oee(hours=hours)
    return {
        "window_hours": hours,
        "availability_pct": oee_data.availability_pct,
        "performance_pct": oee_data.performance_pct,
        "quality_pct": oee_data.quality_pct,
        "oee_pct": oee_data.oee_pct,
        "operating_hours": oee_data.operating_hours,
        "loaded_hours": oee_data.loaded_hours,
        "unloaded_hours": oee_data.unloaded_hours,
        "down_hours": oee_data.down_hours,
        "total_energy_kwh": oee_data.total_energy_kwh,
        "total_air_m3": oee_data.total_air_m3,
        "sec_kwh_per_m3": oee_data.sec_kwh_per_m3
    }

@router.get("/oee/hourly")
def get_hourly_oee(limit: int = Query(24, ge=1, le=72)):
    """Returns hourly OEE records for trend graphs."""
    return oee_engine.get_hourly_trend(limit=limit)

@router.get("/events")
def get_recent_events(limit: int = Query(15, ge=1, le=100), db: Session = Depends(get_db)):
    """Returns recent machine events and alarm notifications."""
    events = db.query(CompressorEvent).filter(
        CompressorEvent.compressor_id == settings.COMPRESSOR_ID
    ).order_by(CompressorEvent.timestamp.desc()).limit(limit).all()

    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "event_type": e.event_type,
            "severity": e.severity,
            "description": e.description,
            "old_state": e.old_state,
            "new_state": e.new_state,
            "fault_code": e.fault_code
        }
        for e in events
    ]

@router.post("/simulator/anomaly")
def inject_anomaly(req: AnomalyRequest):
    """Allows testing fault and warning conditions through the UI."""
    if settings.PLC_ENABLED:
        raise HTTPException(status_code=400, detail="Cannot inject anomaly when connected to physical PLC.")
    simulator.trigger_anomaly(req.anomaly_type)
    return {"message": f"Simulator mode updated to: {req.anomaly_type}"}

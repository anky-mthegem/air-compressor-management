import csv
import io
import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, inspect

from app.config import settings
from app.database.connection import get_db, ACTIVE_DB_DIALECT, engine
from app.database.models import (
    CompressorMaster,
    CompressorTelemetry,
    CompressorEvent,
    CompressorOEEHourly
)

router = APIRouter(prefix="/api/data", tags=["Database Viewer"])

TABLE_MAP = {
    "telemetry": CompressorTelemetry,
    "events": CompressorEvent,
    "oee": CompressorOEEHourly,
    "master": CompressorMaster
}

TABLE_NAMES = {
    "telemetry": "compressor_telemetry",
    "events": "compressor_events",
    "oee": "compressor_oee_hourly",
    "master": "compressor_master"
}

TIMESTAMP_COL_MAP = {
    "telemetry": CompressorTelemetry.timestamp,
    "events": CompressorEvent.timestamp,
    "oee": CompressorOEEHourly.hour_timestamp,
    "master": CompressorMaster.created_at
}

@router.get("/overview")
def get_db_overview(db: Session = Depends(get_db)):
    """Returns database metadata, active engine, and table row counts."""
    counts = {}
    latest_timestamps = {}

    for key, model in TABLE_MAP.items():
        count = db.query(func.count(model.id)).scalar() or 0
        counts[key] = count
        
        # Get latest timestamp
        time_col = TIMESTAMP_COL_MAP.get(key)
        if time_col is not None and count > 0:
            latest_val = db.query(time_col).order_by(time_col.desc()).first()
            if latest_val and latest_val[0]:
                latest_timestamps[key] = latest_val[0].strftime("%Y-%m-%d %H:%M:%S")
            else:
                latest_timestamps[key] = None
        else:
            latest_timestamps[key] = None

    total_rows = sum(counts.values())

    return {
        "status": "ONLINE",
        "active_db": ACTIVE_DB_DIALECT,
        "total_rows": total_rows,
        "tables": {
            "telemetry": {
                "key": "telemetry",
                "table_name": TABLE_NAMES["telemetry"],
                "display_name": "Compressor Telemetry",
                "row_count": counts["telemetry"],
                "latest_timestamp": latest_timestamps["telemetry"],
                "icon": "📈"
            },
            "events": {
                "key": "events",
                "table_name": TABLE_NAMES["events"],
                "display_name": "Events & Alarms Log",
                "row_count": counts["events"],
                "latest_timestamp": latest_timestamps["events"],
                "icon": "⚠️"
            },
            "oee": {
                "key": "oee",
                "table_name": TABLE_NAMES["oee"],
                "display_name": "Hourly OEE History",
                "row_count": counts["oee"],
                "latest_timestamp": latest_timestamps["oee"],
                "icon": "⏱️"
            },
            "master": {
                "key": "master",
                "table_name": TABLE_NAMES["master"],
                "display_name": "Machine Master Config",
                "row_count": counts["master"],
                "latest_timestamp": latest_timestamps["master"],
                "icon": "⚙️"
            }
        }
    }


@router.get("/tables")
def get_table_schemas():
    """Returns column schema definitions for all database tables."""
    schemas = {}
    for key, model in TABLE_MAP.items():
        mapper = inspect(model)
        columns = []
        for col in mapper.columns:
            columns.append({
                "name": col.name,
                "type": str(col.type),
                "nullable": col.nullable,
                "primary_key": col.primary_key
            })
        schemas[key] = {
            "table_name": TABLE_NAMES[key],
            "columns": columns
        }
    return schemas


def _build_filtered_query(
    model,
    key: str,
    time_filter: str,
    start_date: Optional[str],
    end_date: Optional[str],
    search: Optional[str],
    event_severity: Optional[str],
    motor_state: Optional[str],
    db: Session
):
    query = db.query(model)
    time_col = TIMESTAMP_COL_MAP.get(key)

    # 1. Time range filtering
    now = datetime.datetime.utcnow()
    cutoff = None
    if time_filter == "1h":
        cutoff = now - datetime.timedelta(hours=1)
    elif time_filter == "6h":
        cutoff = now - datetime.timedelta(hours=6)
    elif time_filter == "24h":
        cutoff = now - datetime.timedelta(hours=24)
    elif time_filter == "7d":
        cutoff = now - datetime.timedelta(days=7)
    elif time_filter == "30d":
        cutoff = now - datetime.timedelta(days=30)
    elif time_filter == "custom":
        if start_date:
            try:
                s_dt = datetime.datetime.fromisoformat(start_date.replace("Z", "+00:00")).replace(tzinfo=None)
                query = query.filter(time_col >= s_dt)
            except Exception:
                pass
        if end_date:
            try:
                e_dt = datetime.datetime.fromisoformat(end_date.replace("Z", "+00:00")).replace(tzinfo=None)
                query = query.filter(time_col <= e_dt)
            except Exception:
                pass

    if cutoff and time_col is not None:
        query = query.filter(time_col >= cutoff)

    # 2. Contextual filters
    if key == "events":
        if event_severity and event_severity.upper() != "ALL":
            query = query.filter(CompressorEvent.severity == event_severity.upper())
        if search:
            query = query.filter(
                (CompressorEvent.description.ilike(f"%{search}%")) |
                (CompressorEvent.event_type.ilike(f"%{search}%"))
            )
    elif key == "telemetry":
        if motor_state:
            state_lower = motor_state.lower()
            if state_lower == "running":
                query = query.filter(CompressorTelemetry.motor_running == True)
            elif state_lower == "loaded":
                query = query.filter(CompressorTelemetry.loaded == True)
            elif state_lower == "standby":
                query = query.filter(CompressorTelemetry.standby == True)
            elif state_lower == "fault":
                query = query.filter(CompressorTelemetry.fault == True)
    elif key == "master":
        if search:
            query = query.filter(
                (CompressorMaster.tag.ilike(f"%{search}%")) |
                (CompressorMaster.name.ilike(f"%{search}%"))
            )

    return query


def _compute_metrics(key: str, records: List[Any]) -> Dict[str, Any]:
    """Computes summary KPI metrics for the current slice/table."""
    if not records:
        return {}

    if key == "telemetry":
        pressures = [r.discharge_pressure_bar for r in records if r.discharge_pressure_bar is not None]
        powers = [r.active_power_kw for r in records if r.active_power_kw is not None]
        temps = [r.airend_temp_c for r in records if r.airend_temp_c is not None]
        flows = [r.air_flow_cfm for r in records if r.air_flow_cfm is not None]
        
        avg_pressure = round(sum(pressures) / len(pressures), 2) if pressures else 0.0
        max_pressure = round(max(pressures), 2) if pressures else 0.0
        avg_power = round(sum(powers) / len(powers), 2) if powers else 0.0
        max_power = round(max(powers), 2) if powers else 0.0
        avg_temp = round(sum(temps) / len(temps), 1) if temps else 0.0
        max_temp = round(max(temps), 1) if temps else 0.0
        avg_flow = round(sum(flows) / len(flows), 1) if flows else 0.0

        return {
            "avg_discharge_pressure_bar": avg_pressure,
            "max_discharge_pressure_bar": max_pressure,
            "avg_power_kw": avg_power,
            "max_power_kw": max_power,
            "avg_airend_temp_c": avg_temp,
            "max_airend_temp_c": max_temp,
            "avg_flow_cfm": avg_flow,
            "sample_count": len(records)
        }

    elif key == "events":
        critical_count = sum(1 for r in records if r.severity == "CRITICAL")
        warning_count = sum(1 for r in records if r.severity == "WARNING")
        info_count = sum(1 for r in records if r.severity == "INFO")
        return {
            "critical_events": critical_count,
            "warning_events": warning_count,
            "info_events": info_count,
            "total_events": len(records)
        }

    elif key == "oee":
        oees = [r.oee_pct for r in records if r.oee_pct is not None]
        avails = [r.availability_pct for r in records if r.availability_pct is not None]
        perfs = [r.performance_pct for r in records if r.performance_pct is not None]
        quals = [r.quality_pct for r in records if r.quality_pct is not None]
        energies = [r.total_energy_kwh for r in records if r.total_energy_kwh is not None]
        airs = [r.total_air_m3 for r in records if r.total_air_m3 is not None]

        return {
            "avg_oee_pct": round(sum(oees) / len(oees), 1) if oees else 0.0,
            "avg_availability_pct": round(sum(avails) / len(avails), 1) if avails else 0.0,
            "avg_performance_pct": round(sum(perfs) / len(perfs), 1) if perfs else 0.0,
            "avg_quality_pct": round(sum(quals) / len(quals), 1) if quals else 0.0,
            "sum_energy_kwh": round(sum(energies), 1),
            "sum_air_m3": round(sum(airs), 1),
            "total_hours": len(records)
        }

    return {}


def _serialize_row(row: Any) -> Dict[str, Any]:
    """Helper to convert a SQLAlchemy row to a JSON-serializable dictionary with clean formatting."""
    data = {}
    mapper = inspect(row)
    for col in mapper.attrs:
        val = getattr(row, col.key)
        if isinstance(val, datetime.datetime):
            data[col.key] = val.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(val, float):
            data[col.key] = round(val, 2)
        else:
            data[col.key] = val
    return data


@router.get("/records")
def get_table_records(
    table: str = Query("telemetry", pattern="^(telemetry|events|oee|master)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    sort_col: Optional[str] = None,
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    time_filter: str = Query("all", pattern="^(1h|6h|24h|7d|30d|all|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    event_severity: Optional[str] = None,
    motor_state: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Returns paginated, sorted, and filtered records for the selected table."""
    model = TABLE_MAP.get(table)
    if not model:
        raise HTTPException(status_code=400, detail=f"Invalid table '{table}'")

    query = _build_filtered_query(
        model, table, time_filter, start_date, end_date, search, event_severity, motor_state, db
    )

    total_matching = query.count()

    # Determine sorting column
    mapper = inspect(model)
    col_names = [c.name for c in mapper.columns]

    target_col = None
    if sort_col and sort_col in col_names:
        target_col = getattr(model, sort_col)
    else:
        # Default sort column
        time_col = TIMESTAMP_COL_MAP.get(table)
        target_col = time_col if time_col is not None else model.id

    if sort_dir == "asc":
        query = query.order_by(asc(target_col))
    else:
        query = query.order_by(desc(target_col))

    # Calculate pagination
    total_pages = max(1, (total_matching + limit - 1) // limit)
    offset = (page - 1) * limit
    records = query.offset(offset).limit(limit).all()

    # Compute metrics on records
    metrics = _compute_metrics(table, records)

    serialized_rows = [_serialize_row(r) for r in records]

    return {
        "table": table,
        "table_name": TABLE_NAMES[table],
        "page": page,
        "limit": limit,
        "total_records": total_matching,
        "total_pages": total_pages,
        "columns": col_names,
        "rows": serialized_rows,
        "metrics": metrics
    }


@router.get("/export/csv")
def export_table_csv(
    table: str = Query("telemetry", pattern="^(telemetry|events|oee|master)$"),
    time_filter: str = Query("all", pattern="^(1h|6h|24h|7d|30d|all|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    event_severity: Optional[str] = None,
    motor_state: Optional[str] = None,
    max_records: int = Query(5000, ge=1, le=20000),
    db: Session = Depends(get_db)
):
    """Streams matching filtered data directly as a downloadable CSV file."""
    model = TABLE_MAP.get(table)
    if not model:
        raise HTTPException(status_code=400, detail=f"Invalid table '{table}'")

    query = _build_filtered_query(
        model, table, time_filter, start_date, end_date, search, event_severity, motor_state, db
    )

    # Sort descending by timestamp or id
    time_col = TIMESTAMP_COL_MAP.get(table)
    sort_target = time_col if time_col is not None else model.id
    records = query.order_by(desc(sort_target)).limit(max_records).all()

    mapper = inspect(model)
    col_names = [c.name for c in mapper.columns]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(col_names)

    for row in records:
        row_vals = []
        for col in col_names:
            val = getattr(row, col)
            if isinstance(val, datetime.datetime):
                row_vals.append(val.strftime("%Y-%m-%d %H:%M:%S"))
            elif val is None:
                row_vals.append("")
            else:
                row_vals.append(str(val))
        writer.writerow(row_vals)

    output.seek(0)
    filename = f"compressor_{TABLE_NAMES[table]}_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-cache"
        }
    )

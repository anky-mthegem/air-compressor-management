import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Index, Text
)
from sqlalchemy.orm import declarative_base, relationship
from app.utils.time_utils import get_current_time

Base = declarative_base()

class CompressorMaster(Base):
    __tablename__ = "compressor_master"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tag = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    rated_power_kw = Column(Float, default=75.0)
    rated_flow_cfm = Column(Float, default=480.0)
    nominal_pressure_bar = Column(Float, default=7.0)
    created_at = Column(DateTime, default=get_current_time)

    telemetry = relationship("CompressorTelemetry", back_populates="compressor", cascade="all, delete-orphan")


class CompressorTelemetry(Base):
    __tablename__ = "compressor_telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id = Column(Integer, ForeignKey("compressor_master.id"), nullable=False, default=1)
    timestamp = Column(DateTime, default=get_current_time, nullable=False, index=True)

    # Machine States
    motor_running = Column(Boolean, default=False)
    loaded = Column(Boolean, default=False)
    standby = Column(Boolean, default=False)
    fault = Column(Boolean, default=False)
    fault_code = Column(Integer, default=0)

    # Pressures & Temperatures
    discharge_pressure_bar = Column(Float, default=0.0)
    header_pressure_bar = Column(Float, default=0.0)
    airend_temp_c = Column(Float, default=0.0)
    oil_temp_c = Column(Float, default=0.0)
    oil_pressure_bar = Column(Float, default=0.0)
    ambient_temp_c = Column(Float, default=25.0)

    # Differential Pressures (Filter health)
    separator_dp_bar = Column(Float, default=0.25)
    air_filter_dp_mbar = Column(Float, default=15.0)
    oil_filter_dp_bar = Column(Float, default=0.3)

    # Electrical Measurements
    active_power_kw = Column(Float, default=0.0)
    current_a = Column(Float, default=0.0)
    voltage_v = Column(Float, default=415.0)
    power_factor = Column(Float, default=0.88)
    cumulative_energy_kwh = Column(Float, default=0.0)

    # Output & Quality Metrics
    air_flow_cfm = Column(Float, default=0.0)
    dew_point_c = Column(Float, default=2.5)

    # Running Timers
    run_hours = Column(Float, default=0.0)
    loaded_hours = Column(Float, default=0.0)

    compressor = relationship("CompressorMaster", back_populates="telemetry")

    __table_args__ = (
        Index("idx_telemetry_time", "timestamp"),
    )


class CompressorEvent(Base):
    __tablename__ = "compressor_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id = Column(Integer, nullable=False, default=1)
    timestamp = Column(DateTime, default=get_current_time, nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # STATE_CHANGE, WARNING, TRIP, MAINTENANCE
    severity = Column(String(20), default="INFO")    # INFO, WARNING, CRITICAL
    description = Column(String(255), nullable=False)
    old_state = Column(String(50), nullable=True)
    new_state = Column(String(50), nullable=True)
    fault_code = Column(Integer, default=0)


class CompressorOEEHourly(Base):
    __tablename__ = "compressor_oee_hourly"

    id = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id = Column(Integer, nullable=False, default=1)
    hour_timestamp = Column(DateTime, nullable=False, index=True)

    # Time breakdown (minutes)
    planned_minutes = Column(Float, default=60.0)
    operating_minutes = Column(Float, default=0.0)
    loaded_minutes = Column(Float, default=0.0)
    unloaded_minutes = Column(Float, default=0.0)
    down_minutes = Column(Float, default=0.0)

    # Energy & Production
    total_energy_kwh = Column(Float, default=0.0)
    total_air_m3 = Column(Float, default=0.0)
    specific_energy_kwh_m3 = Column(Float, default=0.0)  # SEC

    # OEE Pillars
    availability_pct = Column(Float, default=0.0)
    performance_pct = Column(Float, default=0.0)
    quality_pct = Column(Float, default=0.0)
    oee_pct = Column(Float, default=0.0)

import datetime
import random
import logging
from app.database.models import (
    CompressorMaster, CompressorTelemetry, CompressorEvent, CompressorOEEHourly
)
from app.config import settings
from app.utils.time_utils import get_current_time

logger = logging.getLogger("app.seed")

def seed_initial_data_if_empty():
    from app.database.connection import SessionLocal
    db = SessionLocal()
    try:
        # 1. Ensure master compressor record exists
        master = db.query(CompressorMaster).filter(CompressorMaster.id == settings.COMPRESSOR_ID).first()
        if not master:
            logger.info("Seeding master compressor record...")
            master = CompressorMaster(
                id=settings.COMPRESSOR_ID,
                tag=settings.COMPRESSOR_TAG,
                name=settings.COMPRESSOR_NAME,
                rated_power_kw=settings.RATED_POWER_KW,
                rated_flow_cfm=settings.RATED_FLOW_CFM,
                nominal_pressure_bar=7.0
            )
            db.add(master)
            db.commit()

        # 2. Check if hourly OEE exists for past 24 hours
        oee_count = db.query(CompressorOEEHourly).filter(CompressorOEEHourly.compressor_id == settings.COMPRESSOR_ID).count()
        now = get_current_time().replace(minute=0, second=0, microsecond=0)

        if oee_count < 12:
            logger.info("Generating realistic 24-hour historical OEE and telemetry data...")
            # Generate 24 hours of hourly records
            for h in range(24, 0, -1):
                hour_time = now - datetime.timedelta(hours=h)
                # Realistic shift variation:
                # Night shift: lighter load, slightly lower performance due to unload idling
                is_night = hour_time.hour < 6 or hour_time.hour >= 22
                
                planned_min = 60.0
                down_min = random.choice([0.0, 0.0, 0.0, 2.0, 5.0]) if not is_night else 0.0
                operating_min = planned_min - down_min
                
                if is_night:
                    loaded_ratio = random.uniform(0.55, 0.70)
                else:
                    loaded_ratio = random.uniform(0.75, 0.90)

                loaded_min = round(operating_min * loaded_ratio, 1)
                unloaded_min = round(operating_min - loaded_min, 1)

                # Flow & energy
                avg_flow_cfm = settings.RATED_FLOW_CFM * (loaded_min / 60.0) * random.uniform(0.96, 1.0)
                total_air_m3 = round(avg_flow_cfm * 0.0283168 * 60, 1)
                
                # Power: loaded ~68-74 kW, unloaded ~20-24 kW
                energy_kwh = round((loaded_min / 60.0) * random.uniform(69.0, 74.0) + (unloaded_min / 60.0) * random.uniform(20.0, 23.0), 2)
                sec = round(energy_kwh / total_air_m3, 3) if total_air_m3 > 0 else 0.12

                # OEE Pillars
                avail_pct = round((operating_min / planned_min) * 100.0, 1)
                perf_pct = round((loaded_min / operating_min) * 100.0 * random.uniform(0.97, 1.0), 1)
                quality_pct = round(random.uniform(97.5, 99.8), 1)
                oee_pct = round((avail_pct / 100.0) * (perf_pct / 100.0) * (quality_pct / 100.0) * 100.0, 1)

                oee_entry = CompressorOEEHourly(
                    compressor_id=settings.COMPRESSOR_ID,
                    hour_timestamp=hour_time,
                    planned_minutes=planned_min,
                    operating_minutes=operating_min,
                    loaded_minutes=loaded_min,
                    unloaded_minutes=unloaded_min,
                    down_minutes=down_min,
                    total_energy_kwh=energy_kwh,
                    total_air_m3=total_air_m3,
                    specific_energy_kwh_m3=sec,
                    availability_pct=avail_pct,
                    performance_pct=perf_pct,
                    quality_pct=quality_pct,
                    oee_pct=oee_pct
                )
                db.add(oee_entry)

            # 3. Seed recent telemetry for initial strip chart (last 30 minutes, 1 min step)
            for m in range(30, 0, -1):
                t_time = get_current_time() - datetime.timedelta(minutes=m)
                is_loaded = (m % 5 != 0)
                discharge_p = round(random.uniform(7.1, 7.4) if is_loaded else random.uniform(6.5, 6.8), 2)
                header_p = round(discharge_p - random.uniform(0.2, 0.4), 2)
                airend_t = round(random.uniform(86.0, 91.5) if is_loaded else random.uniform(80.0, 84.0), 1)
                power = round(random.uniform(68.0, 73.5) if is_loaded else random.uniform(21.0, 24.0), 1)
                flow = round(random.uniform(440.0, 475.0) if is_loaded else 0.0, 1)

                telem = CompressorTelemetry(
                    compressor_id=settings.COMPRESSOR_ID,
                    timestamp=t_time,
                    motor_running=True,
                    loaded=is_loaded,
                    standby=False,
                    fault=False,
                    discharge_pressure_bar=discharge_p,
                    header_pressure_bar=header_p,
                    airend_temp_c=airend_t,
                    oil_temp_c=round(airend_t - 8.0, 1),
                    oil_pressure_bar=3.4,
                    separator_dp_bar=0.28,
                    air_filter_dp_mbar=18.0,
                    active_power_kw=power,
                    current_a=round(power * 1.55, 1),
                    voltage_v=412.0,
                    power_factor=0.89 if is_loaded else 0.32,
                    cumulative_energy_kwh=18450.0 + (30 - m) * 1.1,
                    air_flow_cfm=flow,
                    dew_point_c=2.3,
                    run_hours=4280.5 + ((30 - m) / 60.0),
                    loaded_hours=3320.1 + ((30 - m) / 60.0 * 0.8)
                )
                db.add(telem)

            # 4. Seed sample events
            events = [
                CompressorEvent(
                    compressor_id=settings.COMPRESSOR_ID,
                    timestamp=get_current_time() - datetime.timedelta(hours=8),
                    event_type="STATE_CHANGE",
                    severity="INFO",
                    description="Shift 1 Production Started. Compressor auto-loaded.",
                    old_state="STANDBY",
                    new_state="LOADED"
                ),
                CompressorEvent(
                    compressor_id=settings.COMPRESSOR_ID,
                    timestamp=get_current_time() - datetime.timedelta(hours=3, minutes=15),
                    event_type="WARNING",
                    severity="WARNING",
                    description="Air-Oil separator differential pressure reached 0.72 bar (approaching 0.80 bar service threshold).",
                    old_state="LOADED",
                    new_state="LOADED"
                ),
                CompressorEvent(
                    compressor_id=settings.COMPRESSOR_ID,
                    timestamp=get_current_time() - datetime.timedelta(minutes=45),
                    event_type="STATE_CHANGE",
                    severity="INFO",
                    description="Automatic condensate drain valve cycle completed.",
                    old_state="LOADED",
                    new_state="LOADED"
                )
            ]
            for ev in events:
                db.add(ev)

            db.commit()
            logger.info("Initial seed data successfully inserted.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding database: {e}")
    finally:
        db.close()

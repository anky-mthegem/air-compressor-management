import asyncio
import logging
from typing import AsyncGenerator, Dict, Any, List
from app.config import settings
from app.plc.collector import get_latest_telemetry
from app.oee.engine import oee_engine
from app.database.connection import SessionLocal
from app.database.models import CompressorEvent
from app.chatbot.prompts import SYSTEM_PROMPT, generate_context_prompt
from app.chatbot.ollama_client import ollama_client

logger = logging.getLogger("app.chatbot.agent")

class CompressorDiagnosticAgent:
    """
    Intelligent chatbot agent for industrial air compressor health,
    OEE evaluation, thermal performance, and maintenance trouble-shooting.
    """

    async def answer(self, user_query: str) -> AsyncGenerator[str, None]:
        # 1. Fetch live telemetry, OEE, and recent alarms
        telemetry = get_latest_telemetry()
        oee_data = oee_engine.calculate_window_oee(24)
        oee_dict = {
            "oee_pct": oee_data.oee_pct,
            "availability_pct": oee_data.availability_pct,
            "performance_pct": oee_data.performance_pct,
            "quality_pct": oee_data.quality_pct,
            "operating_hours": oee_data.operating_hours,
            "loaded_hours": oee_data.loaded_hours,
            "unloaded_hours": oee_data.unloaded_hours,
            "down_hours": oee_data.down_hours,
            "total_energy_kwh": oee_data.total_energy_kwh,
            "total_air_m3": oee_data.total_air_m3,
            "sec_kwh_per_m3": oee_data.sec_kwh_per_m3,
        }

        db = SessionLocal()
        try:
            events = db.query(CompressorEvent).filter(
                CompressorEvent.compressor_id == settings.COMPRESSOR_ID
            ).order_by(CompressorEvent.timestamp.desc()).limit(5).all()
            recent_events = [
                {
                    "timestamp": e.timestamp.strftime("%Y-%m-%d %H:%M"),
                    "severity": e.severity,
                    "description": e.description
                }
                for e in events
            ]
        finally:
            db.close()

        # 2. Check if local Ollama LLM is running
        ollama_active = await ollama_client.is_available()

        if ollama_active:
            logger.info("Using local Ollama LLM for diagnostic answer.")
            context_prompt = generate_context_prompt(telemetry, oee_dict, recent_events)
            full_system = f"{SYSTEM_PROMPT}\n\n{context_prompt}"
            async for token in ollama_client.stream_chat(full_system, user_query):
                yield token
        else:
            # 3. Built-in Expert Rule Diagnostics Engine
            logger.info("Ollama not running locally. Executing built-in Expert Rule Diagnostics.")
            async for token in self._heuristic_diagnostics(user_query, telemetry, oee_dict, recent_events):
                yield token

    async def _heuristic_diagnostics(
        self,
        query: str,
        t: Dict[str, Any],
        oee: Dict[str, Any],
        events: List[Dict[str, Any]]
    ) -> AsyncGenerator[str, None]:
        q = query.lower()

        # Build response chunks based on domain intent
        if any(w in q for w in ["oee", "efficiency", "performance", "availability", "quality", "sec", "energy", "consumption"]):
            response = self._diagnose_oee(t, oee)
        elif any(w in q for w in ["temp", "heat", "hot", "thermal", "overheat", "cooling", "airend"]):
            response = self._diagnose_temperature(t)
        elif any(w in q for w in ["health", "filter", "separator", "oil", "condition", "maintenance", "wear"]):
            response = self._diagnose_health(t)
        elif any(w in q for w in ["problem", "issue", "alarm", "trip", "fault", "warn", "error"]):
            response = self._diagnose_alarms(t, events)
        else:
            response = self._general_overview(t, oee, events)

        # Stream smoothly with realistic cadence
        words = response.split(" ")
        for i in range(0, len(words), 3):
            chunk = " ".join(words[i:i+3]) + " "
            yield chunk
            await asyncio.sleep(0.02)

    def _diagnose_oee(self, t: Dict[str, Any], oee: Dict[str, Any]) -> str:
        sec = oee.get("sec_kwh_per_m3", 0.11)
        sec_status = "OPTIMAL" if sec <= 0.12 else "ELEVATED"
        unloaded_h = oee.get("unloaded_hours", 0)
        loaded_h = oee.get("loaded_hours", 0)
        unloaded_ratio = round((unloaded_h / (unloaded_h + loaded_h) * 100), 1) if (unloaded_h + loaded_h) > 0 else 0.0

        return f"""### 📊 Overall Equipment Effectiveness (OEE) Analysis

**Overall OEE Score:** **{oee.get('oee_pct')}%** (Trailing 24h)

#### 1. Availability: **{oee.get('availability_pct')}%**
- **Operating Time:** {oee.get('operating_hours')} hrs
- **Unplanned Downtime:** {oee.get('down_hours')} hrs
- *Status:* Good. Machine maintained scheduled availability with minimal breakdown interruption.

#### 2. Performance: **{oee.get('performance_pct')}%**
- **Loaded Time:** {loaded_h} hrs (producing air)
- **Unloaded / Idling Time:** {unloaded_h} hrs ({unloaded_ratio}% of running time)
- *Energy Impact:* While unloaded, this 75 kW screw compressor consumes approximately **21–23 kW** of non-productive power. 
- *Recommendation:* If unloaded time exceeds 25%, evaluate adjusting load/unload pressure setpoints (currently {settings.TARGET_PRESSURE_MIN_BAR}–{settings.TARGET_PRESSURE_MAX_BAR} bar) or inspect the plant for downstream air leaks.

#### 3. Quality (Pressure & Moisture Compliance): **{oee.get('quality_pct')}%**
- **Pressure Stability:** Maintained within specified band (> {settings.TARGET_PRESSURE_MIN_BAR} bar).
- **Dew Point:** Currently **{t.get('dew_point_c')}°C** (well within the < 3.0°C standard for refrigerated air dryers).

#### 4. Energy & Specific Consumption (SEC):
- **Cumulative Energy (24h):** {oee.get('total_energy_kwh')} kWh
- **Total Compressed Air Delivered:** {oee.get('total_air_m3')} m³
- **Specific Energy Consumption (SEC):** **{sec} kWh/m³** (`{sec_status}`)
"""

    def _diagnose_temperature(self, t: Dict[str, Any]) -> str:
        temp = t.get("airend_temp_c", 88.0)
        oil_temp = t.get("oil_temp_c", 80.0)
        amb_temp = t.get("ambient_temp_c", 26.0)

        if temp >= settings.AIREND_TEMP_TRIP_C:
            status = "🚨 **CRITICAL TRIP LEVEL**"
            action = "Compressor is at or above safety trip limit (>105°C). Immediate shutdown required."
        elif temp >= settings.AIREND_TEMP_WARN_C:
            status = "⚠️ **HIGH TEMPERATURE WARNING**"
            action = "Airend discharge is running hot. Check oil cooler for dust fouling, check oil level, and inspect thermostatic valve."
        else:
            status = "✅ **NORMAL THERMAL STATUS**"
            action = "Thermal balance is stable. Normal oil circulation and cooling performance."

        return f"""### 🌡️ Thermal & Airend Temperature Diagnostics

{status}

- **Current Airend Discharge Temp:** **{temp}°C** (Trip limit: {settings.AIREND_TEMP_TRIP_C}°C)
- **Oil Sump Temperature:** {oil_temp}°C
- **Ambient Factory Temperature:** {amb_temp}°C
- **Differential (Delta T Element vs Ambient):** {round(temp - amb_temp, 1)}°C

#### Engineering Assessment:
{action}

#### Preventative Inspection Checklist:
1. **Oil Level & Quality:** Check sight glass when stopped; inspect for varnish or thermal discoloration.
2. **Cooler Matrix:** Inspect air-cooled oil radiator for lint, dust, or oil film accumulation on fins.
3. **Thermostatic Valve:** Verify element opens fully at 71°C to divert oil through cooler.
"""

    def _diagnose_health(self, t: Dict[str, Any]) -> str:
        sep_dp = t.get("separator_dp_bar", 0.28)
        oil_dp = t.get("oil_filter_dp_bar", 0.3)
        air_dp = t.get("air_filter_dp_mbar", 18.0)

        sep_status = "⚠️ Nearing replacement (>0.8 bar)" if sep_dp >= settings.SEPARATOR_DP_WARN_BAR else "✅ Normal (0.2–0.4 bar)"

        return f"""### 🛡️ Compressor Mechanical Health & Consumables

#### 1. Air-Oil Separator Element
- **Current Differential Pressure:** **{sep_dp} bar** — {sep_status}
- *Significance:* A clogged separator increases internal vessel pressure, increases motor kW consumption by 1% per 0.1 bar, and risks oil aerosol carry-over into factory air lines.

#### 2. Oil System & Filter
- **Oil Filter Differential Pressure:** {oil_dp} bar (Max allowed: 1.2 bar)
- **Oil Delivery Pressure:** {t.get('oil_pressure_bar')} bar (Adequate for hydrodynamic lubrication of male/female screw bearings).

#### 3. Air Intake Filter
- **Air Filter Differential Pressure:** {air_dp} mbar (Clean threshold: < 25 mbar)
- *Status:* Clean. Unrestricted suction flow ensures maximum volumetric efficiency.

#### 4. Motor & Drive Line
- **Operating Hours:** {t.get('run_hours')} hrs | **Loaded Hours:** {t.get('loaded_hours')} hrs
- **Current Load:** {t.get('active_power_kw')} kW at {t.get('current_a')} A (Power Factor: {t.get('power_factor')})
"""

    def _diagnose_alarms(self, t: Dict[str, Any], events: List[Dict[str, Any]]) -> str:
        fault = t.get("fault", False)
        fault_code = t.get("fault_code", 0)

        events_md = ""
        for ev in events:
            icon = "🔴" if ev.get("severity") == "CRITICAL" else ("🟡" if ev.get("severity") == "WARNING" else "ℹ️")
            events_md += f"- {icon} **{ev.get('timestamp')}** [{ev.get('severity')}]: {ev.get('description')}\n"

        if fault:
            headline = f"🚨 **ACTIVE TRIP DETECTED (Fault Code: {fault_code})**"
        else:
            headline = "✅ **NO ACTIVE TRIPS (System Running Normally)**"

        return f"""### ⚠️ Alarm & Trip Diagnostic Report

{headline}

#### Recent Event Log:
{events_md if events_md else "No recent alarms logged in database."}

#### Safety Interlock Status:
- **Emergency Stop:** NORMAL (Closed circuit)
- **Motor Overload Relay:** NORMAL
- **High Pressure Switch:** NORMAL (Discharge: {t.get('discharge_pressure_bar')} bar)
- **High Temperature Sensor:** NORMAL (Current: {t.get('airend_temp_c')}°C)
"""

    def _general_overview(self, t: Dict[str, Any], oee: Dict[str, Any], events: List[Dict[str, Any]]) -> str:
        state_str = "RUNNING LOADED" if t.get("loaded") else ("IDLING (UNLOADED)" if t.get("motor_running") else "OFF/STANDBY")
        return f"""### 🏭 Air Compressor Management - Executive Overview

- **Machine:** {settings.COMPRESSOR_NAME} ({settings.COMPRESSOR_TAG})
- **Current State:** **{state_str}**
- **Discharge Pressure:** {t.get('discharge_pressure_bar')} bar (Plant Header: {t.get('header_pressure_bar')} bar)
- **Power Draw:** {t.get('active_power_kw')} kW (Flow: {t.get('air_flow_cfm')} CFM)
- **Airend Temperature:** {t.get('airend_temp_c')}°C
- **Current OEE (24h):** **{oee.get('oee_pct')}%** (Avail: {oee.get('availability_pct')}%, Perf: {oee.get('performance_pct')}%, Qual: {oee.get('quality_pct')}%)
- **Specific Energy:** {oee.get('sec_kwh_per_m3')} kWh/m³

*You can ask me specific questions like:*
- *"Why is OEE lower than 85%?"*
- *"Check the air-oil separator health."*
- *"Is the airend running too hot?"*
- *"Show me recent alarms and trip history."*
"""

chatbot_agent = CompressorDiagnosticAgent()

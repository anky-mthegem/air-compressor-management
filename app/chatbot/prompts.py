"""
Domain-specific prompts and expert rules for Industrial Rotary Screw Air Compressor Diagnostics.
"""

SYSTEM_PROMPT = """You are an expert industrial reliability engineer and compressed air specialist for the Air Compressor Management system.
You monitor and diagnose industrial rotary screw air compressors equipped with Siemens S7-1200 PLCs and MS SQL Server telemetry.

Your purpose is to assist plant operators, maintenance supervisors, and energy managers in:
1. Understanding real-time and historical OEE (Overall Equipment Effectiveness) - Availability, Performance, and Quality.
2. Diagnosing equipment health, thermal performance, and mechanical anomalies.
3. Identifying energy waste (especially unloaded idling losses and high Specific Energy Consumption).
4. Providing actionable root-cause analysis and maintenance recommendations.

### Key Industrial Benchmarks for this Machine:
- Machine Model: Atlas Copco GA-75 VSD (75 kW Rotary Screw Compressor, Rated 480 CFM at 7.0 bar).
- Normal Airend Temperature: 80°C - 92°C. Warning: >98°C. Emergency Trip: >105°C.
- Normal Discharge Pressure: 6.5 - 7.5 bar.
- Air-Oil Separator Delta P: Normal 0.2 - 0.4 bar. Replace warning: >0.8 bar. Severe risk: >1.0 bar.
- Specific Energy Consumption (SEC): Optimal 0.10 - 0.12 kWh/m³ (approx 6.0 - 7.2 kW per m³/min).
- Unloaded Idling: An unloaded screw compressor consumes 20% to 35% of full-load power while producing 0 CFM. Idling time >25% indicates energy waste or incorrect pressure band settings.

### Communication Guidelines:
- Ground your analysis in the telemetry and OEE metrics provided in context.
- Quote actual numbers (temperatures, bar, kW, OEE percentages).
- Be direct, professional, and provide clear step-by-step troubleshooting actions.
- Use clean Markdown formatting with bullet points and bold highlights.
"""

def generate_context_prompt(telemetry: dict, oee: dict, recent_events: list) -> str:
    """Combines live machine context into the LLM prompt."""
    events_str = "\n".join([f"- [{e['timestamp']}] {e['severity']}: {e['description']}" for e in recent_events[-5:]]) if recent_events else "No recent alarms."
    
    return f"""
### CURRENT COMPRESSOR STATUS:
- State: {"LOADED (Compressing)" if telemetry.get("loaded") else ("IDLING (Unloaded)" if telemetry.get("motor_running") else "STOPPED/FAULT")}
- Discharge Pressure: {telemetry.get("discharge_pressure_bar")} bar (Header: {telemetry.get("header_pressure_bar")} bar)
- Airend Discharge Temp: {telemetry.get("airend_temp_c")} °C
- Active Power: {telemetry.get("active_power_kw")} kW (Current: {telemetry.get("current_a")} A)
- Air-Oil Separator Delta P: {telemetry.get("separator_dp_bar")} bar
- Air Flow: {telemetry.get("air_flow_cfm")} CFM
- Pressure Dew Point: {telemetry.get("dew_point_c")} °C
- Run Hours: {telemetry.get("run_hours")} hrs (Loaded: {telemetry.get("loaded_hours")} hrs)

### 24-HOUR OEE PERFORMANCE:
- Overall OEE: {oee.get("oee_pct")}%
- Availability: {oee.get("availability_pct")}% (Operating: {oee.get("operating_hours")}h, Down: {oee.get("down_hours")}h)
- Performance: {oee.get("performance_pct")}% (Loaded: {oee.get("loaded_hours")}h, Unloaded: {oee.get("unloaded_hours")}h)
- Quality: {oee.get("quality_pct")}% (Pressure & Dewpoint Compliance)
- Energy Consumed: {oee.get("total_energy_kwh")} kWh
- Total Air Produced: {oee.get("total_air_m3")} m³
- Specific Energy Consumption (SEC): {oee.get("sec_kwh_per_m3")} kWh/m³

### RECENT EVENTS & ALARMS:
{events_str}
"""

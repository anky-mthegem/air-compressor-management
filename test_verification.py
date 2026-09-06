import sys
import os
import asyncio
from pathlib import Path
import httpx

# Ensure UTF-8 output on Windows terminal
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app.config import settings
from app.database.connection import init_db, SessionLocal, ACTIVE_DB_DIALECT
from app.database.models import CompressorMaster, CompressorTelemetry, CompressorOEEHourly, CompressorEvent
from app.plc.simulator import simulator
from app.plc.collector import plc_collector
from app.oee.engine import oee_engine
from app.chatbot.agent import chatbot_agent
from run import app

async def run_tests():
    print("==================================================")
    print(" RUNNING AIR COMPRESSOR MANAGEMENT VERIFICATION")
    print("==================================================")

    # 1. Test Database Initialization & Seeding
    print("\n[TEST 1] Initializing Database & Seeding...")
    init_db()
    print(f"Active DB Dialect: {ACTIVE_DB_DIALECT}")

    db = SessionLocal()
    try:
        master = db.query(CompressorMaster).first()
        assert master is not None, "Master compressor record missing!"
        print(f" Master record verified: {master.tag} - {master.name}")

        telem_count = db.query(CompressorTelemetry).count()
        assert telem_count > 0, "No telemetry records seeded!"
        print(f" Telemetry table verified: {telem_count} records present.")

        oee_count = db.query(CompressorOEEHourly).count()
        assert oee_count > 0, "No hourly OEE records seeded!"
        print(f" Hourly OEE table verified: {oee_count} hourly records present.")

        event_count = db.query(CompressorEvent).count()
        assert event_count > 0, "No event records seeded!"
        print(f" Event log table verified: {event_count} events present.")
    finally:
        db.close()

    # 2. Test Simulator Physics
    print("\n[TEST 2] Testing Simulator Physics...")
    t1 = simulator.tick(2.0)
    assert t1["discharge_pressure_bar"] > 0, "Simulator pressure invalid"
    assert t1["active_power_kw"] > 0, "Simulator active power invalid"
    print(f" Simulator tick OK: Pressure = {t1['discharge_pressure_bar']} bar, Power = {t1['active_power_kw']} kW, State = {'LOADED' if t1['loaded'] else 'UNLOADED'}")

    # 3. Test OEE Calculations
    print("\n[TEST 3] Testing OEE Engine Calculations...")
    oee = oee_engine.calculate_window_oee(24)
    assert 0 <= oee.oee_pct <= 100, f"Invalid OEE %: {oee.oee_pct}"
    assert 0 <= oee.availability_pct <= 100, f"Invalid Availability %: {oee.availability_pct}"
    assert 0 <= oee.performance_pct <= 100, f"Invalid Performance %: {oee.performance_pct}"
    assert 0 <= oee.quality_pct <= 100, f"Invalid Quality %: {oee.quality_pct}"
    assert oee.sec_kwh_per_m3 > 0, "Invalid SEC metric"
    print(f" OEE Math OK: Overall OEE = {oee.oee_pct}%, Availability = {oee.availability_pct}%, Performance = {oee.performance_pct}%, Quality = {oee.quality_pct}%, SEC = {oee.sec_kwh_per_m3} kWh/m³")

    # 4. Test Local AI Diagnostics Chatbot
    print("\n[TEST 4] Testing Local AI Diagnostics Chatbot...")
    query = "Analyze today's OEE and tell me if the airend temperature is safe."
    print(f"User Query: '{query}'")
    chunks = []
    async for token in chatbot_agent.answer(query):
        chunks.append(token)
    response = "".join(chunks)
    assert len(response) > 50, "Chatbot response too short!"
    print(f" Chatbot streaming generated {len(chunks)} tokens ({len(response)} characters).")

    # 5. Test REST & Template Endpoints via ASGI test client
    print("\n[TEST 5] Testing Endpoints & Siemens S7-1200 Diagnostics...")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Dashboard HTML
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "Air Compressor Management" in resp.text
        print(" GET / -> 200 OK (Cockpit UI served)")

        # PLC Diagnostics Page
        resp = await client.get("/plc")
        assert resp.status_code == 200
        assert "PLC Communication & Diagnostics" in resp.text
        print(" GET /plc -> 200 OK (Siemens S7-1200 Diagnostics Page served)")

        # PLC Status API
        resp = await client.get("/api/plc/status")
        assert resp.status_code == 200
        plc_stat = resp.json()
        assert "status" in plc_stat
        assert "handshake" in plc_stat
        print(f" GET /api/plc/status -> 200 OK (Status: {plc_stat['status']}, Heartbeat: {plc_stat['handshake']['plc_counter']})")

        # PLC Datapoints Table API
        resp = await client.get("/api/plc/datapoints")
        assert resp.status_code == 200
        datapoints = resp.json()
        assert len(datapoints) >= 22, f"Expected >= 22 datapoints, got {len(datapoints)}"
        dbw70 = next((dp for dp in datapoints if dp["offset"] == "DB1.DBW70"), None)
        assert dbw70 is not None, "Heartbeat watchdog counter DB1.DBW70 missing!"
        print(f" GET /api/plc/datapoints -> 200 OK ({len(datapoints)} S7-1200 registers verified including {dbw70['offset']})")

        # Handshake Config API
        resp = await client.post("/api/plc/handshake/config", json={"enabled": True, "timeout_sec": 4.5})
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["timeout_sec"] == 4.5
        print(f" POST /api/plc/handshake/config -> 200 OK (Updated timeout to {cfg['timeout_sec']}s)")

        # Simulate Disconnect API
        resp = await client.post("/api/plc/simulate_disconnect", json={"simulate_disconnect": True})
        assert resp.status_code == 200
        print(" POST /api/plc/simulate_disconnect -> 200 OK (Triggered simulated disconnect)")

        # Verify Disconnected Status
        resp = await client.get("/api/plc/status")
        assert resp.json()["status"] == "DISCONNECTED"
        print(" Disconnection status verified -> DISCONNECTED")

        # Reconnect API
        resp = await client.post("/api/plc/reconnect")
        assert resp.status_code == 200
        resp = await client.get("/api/plc/status")
        assert resp.json()["status"] == "CONNECTED"
        print(" POST /api/plc/reconnect -> 200 OK (Restored status to CONNECTED)")

        # Probe Socket API
        resp = await client.post("/api/plc/probe")
        assert resp.status_code == 200
        probe = resp.json()
        assert "port_102_open" in probe
        print(f" POST /api/plc/probe -> 200 OK ({probe['diagnostic_message']})")

        # 6. Test SQL Database Viewer UI & Endpoints
        print("\n[TEST 6] Testing SQL Database Viewer Endpoints...")
        # Data Viewer HTML page
        resp = await client.get("/data")
        assert resp.status_code == 200
        assert "SQL Database Historian" in resp.text
        assert "scadaDataTable" in resp.text
        print(" GET /data -> 200 OK (SQL Database Viewer UI served)")

        # Database Overview API
        resp = await client.get("/api/data/overview")
        assert resp.status_code == 200
        overview = resp.json()
        assert "tables" in overview
        assert overview["total_rows"] > 0
        assert overview["tables"]["telemetry"]["row_count"] > 0
        assert overview["tables"]["events"]["row_count"] > 0
        assert overview["tables"]["oee"]["row_count"] > 0
        assert overview["tables"]["master"]["row_count"] > 0
        print(f" GET /api/data/overview -> 200 OK (Dialect: {overview['active_db']}, Total Rows: {overview['total_rows']})")

        # Table Schemas API
        resp = await client.get("/api/data/tables")
        assert resp.status_code == 200
        schemas = resp.json()
        assert "telemetry" in schemas
        assert len(schemas["telemetry"]["columns"]) >= 20
        print(f" GET /api/data/tables -> 200 OK (Schemas verified for {list(schemas.keys())})")

        # Table Records Query API (Telemetry)
        resp = await client.get("/api/data/records?table=telemetry&limit=15&page=1")
        assert resp.status_code == 200
        records = resp.json()
        assert records["table"] == "telemetry"
        assert len(records["rows"]) <= 15
        assert "discharge_pressure_bar" in records["columns"]
        assert "avg_discharge_pressure_bar" in records["metrics"]
        print(f" GET /api/data/records (telemetry) -> 200 OK ({len(records['rows'])} rows returned, Avg P: {records['metrics']['avg_discharge_pressure_bar']} bar)")

        # Table Records Query API (Events)
        resp = await client.get("/api/data/records?table=events&limit=10")
        assert resp.status_code == 200
        ev_records = resp.json()
        assert ev_records["table"] == "events"
        assert len(ev_records["rows"]) > 0
        assert "critical_events" in ev_records["metrics"]
        print(f" GET /api/data/records (events) -> 200 OK ({len(ev_records['rows'])} event logs, Total: {ev_records['total_records']})")

        # Table Records Query API (OEE Hourly)
        resp = await client.get("/api/data/records?table=oee&limit=10")
        assert resp.status_code == 200
        oee_records = resp.json()
        assert oee_records["table"] == "oee"
        assert len(oee_records["rows"]) > 0
        assert "avg_oee_pct" in oee_records["metrics"]
        print(f" GET /api/data/records (oee) -> 200 OK (Avg OEE: {oee_records['metrics']['avg_oee_pct']}%)")

        # Table CSV Export API
        resp = await client.get("/api/data/export/csv?table=telemetry&max_records=50")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        csv_lines = resp.text.strip().split("\r\n" if "\r\n" in resp.text else "\n")
        assert len(csv_lines) > 1, "CSV empty or missing header!"
        assert "discharge_pressure_bar" in csv_lines[0]
        print(f" GET /api/data/export/csv (telemetry) -> 200 OK ({len(csv_lines)} CSV lines generated)")

    print("\n==================================================")
    print(" ALL VERIFICATION SUITES PASSED FLAWLESSLY! ")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())

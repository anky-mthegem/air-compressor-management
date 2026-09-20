"""
Migration script to adjust existing timestamps in data/compressor.db from UTC to IST (+05:30).
"""
import shutil
import sqlite3
import datetime
from pathlib import Path

DB_PATH = Path("data/compressor.db")
BACKUP_PATH = Path("data/compressor.db.bak")

def parse_and_shift(dt_str: str, delta: datetime.timedelta) -> str:
    if not dt_str:
        return dt_str
    # Try different format parses
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(dt_str, fmt)
            new_dt = dt + delta
            return new_dt.strftime(fmt)
        except ValueError:
            pass
    return dt_str

def main():
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    # Backup database
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"Created backup at {BACKUP_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    delta = datetime.timedelta(hours=5, minutes=30)

    # 1. Shift telemetry
    rows = cur.execute("SELECT id, timestamp FROM compressor_telemetry").fetchall()
    for row_id, ts in rows:
        new_ts = parse_and_shift(ts, delta)
        cur.execute("UPDATE compressor_telemetry SET timestamp = ? WHERE id = ?", (new_ts, row_id))
    print(f"Shifted {len(rows)} telemetry timestamps by +5h 30m.")

    # 2. Shift events
    rows = cur.execute("SELECT id, timestamp FROM compressor_events").fetchall()
    for row_id, ts in rows:
        new_ts = parse_and_shift(ts, delta)
        cur.execute("UPDATE compressor_events SET timestamp = ? WHERE id = ?", (new_ts, row_id))
    print(f"Shifted {len(rows)} event timestamps by +5h 30m.")

    # 3. Shift OEE
    rows = cur.execute("SELECT id, hour_timestamp FROM compressor_oee_hourly").fetchall()
    for row_id, ts in rows:
        new_ts = parse_and_shift(ts, delta)
        cur.execute("UPDATE compressor_oee_hourly SET hour_timestamp = ? WHERE id = ?", (new_ts, row_id))
    print(f"Shifted {len(rows)} hourly OEE timestamps by +5h 30m.")

    # 4. Shift master
    rows = cur.execute("SELECT id, created_at FROM compressor_master").fetchall()
    for row_id, ts in rows:
        new_ts = parse_and_shift(ts, delta)
        cur.execute("UPDATE compressor_master SET created_at = ? WHERE id = ?", (new_ts, row_id))
    print(f"Shifted {len(rows)} master records by +5h 30m.")

    conn.commit()

    # Print new min/max
    print("\n--- Migration Complete ---")
    print("New Telem min/max:", cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM compressor_telemetry").fetchone())
    print("New Events min/max:", cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM compressor_events").fetchone())
    print("New OEE min/max:", cur.execute("SELECT MIN(hour_timestamp), MAX(hour_timestamp) FROM compressor_oee_hourly").fetchone())

    conn.close()

if __name__ == "__main__":
    main()

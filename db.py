import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "travel.db"  # db.py lives in backend/; the DB stays at the project root


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            traveler_name TEXT NOT NULL,
            origin TEXT,
            destination TEXT,
            start_date TEXT,
            end_date TEXT,
            start_time TEXT,
            end_time TEXT,
            start_arrival_time TEXT,
            end_departure_time TEXT,
            airline TEXT,
            booking_source TEXT,
            pnr TEXT,
            price TEXT,
            status TEXT NOT NULL DEFAULT 'confirmed',
            outbound_status TEXT NOT NULL DEFAULT 'confirmed',
            return_status TEXT NOT NULL DEFAULT 'confirmed',
            source_format TEXT,
            needs_review INTEGER NOT NULL DEFAULT 0,
            source_file TEXT,
            drive_file_id TEXT,
            drive_view_link TEXT,
            drive_managed INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trips)")}
    for col in (
        "start_time", "end_time", "drive_file_id", "drive_view_link", "price",
        "start_arrival_time", "end_departure_time", "booking_source",
    ):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE trips ADD COLUMN {col} TEXT")
    if "drive_managed" not in existing_cols:
        conn.execute("ALTER TABLE trips ADD COLUMN drive_managed INTEGER NOT NULL DEFAULT 0")
    for leg_col in ("outbound_status", "return_status"):
        if leg_col not in existing_cols:
            conn.execute(f"ALTER TABLE trips ADD COLUMN {leg_col} TEXT NOT NULL DEFAULT 'confirmed'")
            # Keep pre-existing cancelled trips consistent: both legs were
            # cancelled together before per-leg cancellation existed.
            conn.execute(f"UPDATE trips SET {leg_col} = status WHERE status = 'cancelled'")
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

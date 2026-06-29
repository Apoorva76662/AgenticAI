"""SQLite schema creation + idempotent seed data.

Run directly to (re)build the database:
    python -m leave_agent.database          # from the repo root
    # or
    python leave_agent/database.py

Idempotent: safe to re-run. It DROPs and recreates the seed-controlled
tables so the demo always starts from a known state.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

# DB lives next to this file unless overridden. .gitignore should exclude it.
DB_PATH = os.environ.get(
    "LEAVE_DB_PATH",
    os.path.join(os.path.dirname(__file__), "leave.db"),
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS employees (
    employee_id   TEXT PRIMARY KEY,
    full_name     TEXT NOT NULL,
    department    TEXT,
    country_code  TEXT NOT NULL,          -- ISO 3166-1 alpha-2
    join_date     DATE,
    manager_id    TEXT REFERENCES employees(employee_id)
);

CREATE TABLE IF NOT EXISTS leave_balances (
    balance_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     TEXT NOT NULL REFERENCES employees(employee_id),
    leave_type      TEXT NOT NULL,        -- ANNUAL | SICK | PERSONAL
    year            INTEGER NOT NULL,
    total_days      REAL NOT NULL,
    used_days       REAL NOT NULL DEFAULT 0,
    available_days  REAL NOT NULL,        -- maintained = total_days - used_days
    UNIQUE (employee_id, leave_type, year)
);

CREATE TABLE IF NOT EXISTS public_holidays (
    holiday_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code  TEXT NOT NULL,
    holiday_date  DATE NOT NULL,
    holiday_name  TEXT NOT NULL,
    UNIQUE (country_code, holiday_date)
);

CREATE TABLE IF NOT EXISTS leave_requests (
    request_id    TEXT PRIMARY KEY,       -- e.g. LR-2025-0001
    employee_id   TEXT NOT NULL REFERENCES employees(employee_id),
    leave_type    TEXT NOT NULL,
    start_date    DATE NOT NULL,
    end_date      DATE NOT NULL,
    working_days  REAL NOT NULL,
    status        TEXT NOT NULL,          -- PENDING | APPROVED | REJECTED | CANCELLED
    submitted_at  DATETIME NOT NULL,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_holidays_country_date
    ON public_holidays (country_code, holiday_date);
CREATE INDEX IF NOT EXISTS idx_requests_employee
    ON leave_requests (employee_id, status);
"""

# --- Seed data -------------------------------------------------------------
# 5 employees across 2 countries (IN, GB). EMP-003 = Sarah Nguyen (GB) so the
# document's Prompt 1 (EMP-003) and Prompt 2 (Sarah Nguyen) hit the same person.
EMPLOYEES = [
    # Managers first so the self-referencing manager_id FK resolves on insert.
    # id,       full_name,       department,        country, join_date,    manager
    ("EMP-004", "Emily Clarke",  "Engineering Lead","GB", "2018-05-20", None),
    ("EMP-005", "Vikram Rao",    "Operations Lead", "IN", "2017-09-05", None),
    ("EMP-001", "Arjun Mehta",   "Engineering",     "IN", "2021-03-01", "EMP-005"),
    ("EMP-002", "Rahul Verma",   "Sales",           "IN", "2022-07-15", "EMP-005"),
    ("EMP-003", "Sarah Nguyen",  "Engineering",     "GB", "2020-01-10", "EMP-004"),
]

# Balances seeded for 2025 and 2026 

def _balances():
    rows = []
    for year in (2025, 2026):
        rows += [
            ("EMP-001", "ANNUAL", year, 24, 5, 19),
            ("EMP-001", "SICK",   year, 12, 2, 10),
            ("EMP-002", "ANNUAL", year, 20, 6, 14),   # < ~21 working days -> insufficient
            ("EMP-002", "SICK",   year, 12, 0, 12),
            ("EMP-003", "ANNUAL", year, 25, 8, 17),
            ("EMP-003", "SICK",   year, 10, 1, 9),
            ("EMP-004", "ANNUAL", year, 28, 4, 24),
            ("EMP-004", "SICK",   year, 10, 0, 10),
            ("EMP-005", "ANNUAL", year, 26, 10, 16),
            ("EMP-005", "SICK",   year, 12, 3, 9),
        ]
    return rows

HOLIDAYS = [
    # India (IN) — 2025
    ("IN", "2025-01-26", "Republic Day"),
    ("IN", "2025-03-14", "Holi"),
    ("IN", "2025-08-15", "Independence Day"),
    ("IN", "2025-10-02", "Gandhi Jayanti"),
    ("IN", "2025-10-21", "Diwali"),
    ("IN", "2025-12-25", "Christmas Day"),
    ("IN", "2025-04-18", "Good Friday"),
    ("IN", "2025-05-01", "Labour Day"),
    # India (IN) — 2026
    ("IN", "2026-01-26", "Republic Day"),
    ("IN", "2026-08-15", "Independence Day"),
    ("IN", "2026-10-02", "Gandhi Jayanti"),
    ("IN", "2026-11-08", "Diwali"),
    ("IN", "2026-12-25", "Christmas Day"),
    ("IN", "2026-05-01", "Labour Day"),
    ("IN", "2026-03-04", "Holi"),
    ("IN", "2026-04-03", "Good Friday"),
    # United Kingdom (GB) — 2025
    ("GB", "2025-01-01", "New Year's Day"),
    ("GB", "2025-04-18", "Good Friday"),
    ("GB", "2025-04-21", "Easter Monday"),
    ("GB", "2025-05-05", "Early May Bank Holiday"),
    ("GB", "2025-05-26", "Spring Bank Holiday"),
    ("GB", "2025-08-25", "Summer Bank Holiday"),
    ("GB", "2025-12-25", "Christmas Day"),
    ("GB", "2025-12-26", "Boxing Day"),
    # United Kingdom (GB) — 2026 
    ("GB", "2026-01-01", "New Year's Day"),
    ("GB", "2026-04-03", "Good Friday"),
    ("GB", "2026-04-06", "Easter Monday"),
    ("GB", "2026-05-04", "Early May Bank Holiday"),
    ("GB", "2026-05-25", "Spring Bank Holiday"),
    ("GB", "2026-08-31", "Summer Bank Holiday"),
    ("GB", "2026-12-25", "Christmas Day"),
    ("GB", "2026-12-28", "Boxing Day (substitute)"),
]

# 2 existing requests: one APPROVED (history), one PENDING.
LEAVE_REQUESTS = [
    ("LR-2025-0001", "EMP-001", "ANNUAL", "2025-02-10", "2025-02-14",
     5, "APPROVED", "2025-01-20 09:30:00", "Family trip"),
    ("LR-2025-0002", "EMP-002", "SICK", "2025-03-03", "2025-03-04",
     2, "PENDING", "2025-03-02 18:05:00", "Flu"),
]


def init_db(db_path: str = DB_PATH) -> str:
    """Create schema and (re)seed. Idempotent."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    # Reset seed-controlled tables for a deterministic demo start state.
    for t in ("leave_requests", "public_holidays", "leave_balances", "employees"):
        cur.execute(f"DELETE FROM {t}")

    cur.executemany(
        "INSERT INTO employees VALUES (?,?,?,?,?,?)", EMPLOYEES
    )
    cur.executemany(
        "INSERT INTO leave_balances "
        "(employee_id, leave_type, year, total_days, used_days, available_days) "
        "VALUES (?,?,?,?,?,?)",
        _balances(),
    )
    cur.executemany(
        "INSERT INTO public_holidays (country_code, holiday_date, holiday_name) "
        "VALUES (?,?,?)",
        HOLIDAYS,
    )
    cur.executemany(
        "INSERT INTO leave_requests "
        "(request_id, employee_id, leave_type, start_date, end_date, "
        " working_days, status, submitted_at, notes) VALUES (?,?,?,?,?,?,?,?,?)",
        LEAVE_REQUESTS,
    )
    conn.commit()
    conn.close()
    return db_path


def ensure_db(db_path: str = DB_PATH) -> None:
    """Build the DB if it's missing or unseeded. Lets a fresh managed-runtime
    container (e.g. Vertex AI Agent Engine) come up without a manual seed step.
    Note: SQLite on a managed/ephemeral filesystem is per-instance and not
    durable across replicas — fine for a demo, swap for Cloud SQL for real use.
    """
    if not os.path.exists(db_path):
        init_db(db_path)
        return
    try:
        conn = sqlite3.connect(db_path)
        seeded = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        conn.close()
        if not seeded:
            init_db(db_path)
    except sqlite3.OperationalError:
        init_db(db_path)  # tables don't exist yet


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    ensure_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    path = init_db()
    print(f"Initialised database at: {path}")

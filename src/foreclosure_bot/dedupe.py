import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_number     TEXT PRIMARY KEY,
    date_filed      DATE NOT NULL,
    tax_map_number  TEXT,
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

CREATE TABLE IF NOT EXISTS parcels (
    tax_map_number  TEXT PRIMARY KEY,
    owner_raw       TEXT,
    site_street     TEXT,
    site_city       TEXT,
    site_state      TEXT,
    site_zip        TEXT,
    resolved_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skip_traces (
    id              INTEGER PRIMARY KEY,
    person_key      TEXT NOT NULL UNIQUE,
    owner_name      TEXT NOT NULL,
    site_street     TEXT,
    site_city       TEXT,
    site_state      TEXT,
    site_zip        TEXT,
    mobiles_json    TEXT,
    traced_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sheet_rows (
    id              INTEGER PRIMARY KEY,
    case_number     TEXT NOT NULL,
    person_key      TEXT NOT NULL,
    written_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_number, person_key)
);

CREATE TABLE IF NOT EXISTS errors (
    id              INTEGER PRIMARY KEY,
    occurred_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stage           TEXT,
    case_number     TEXT,
    message         TEXT,
    traceback       TEXT
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

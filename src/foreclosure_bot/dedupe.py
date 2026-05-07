import json
import sqlite3
from pathlib import Path
from .models import Case, Parcel

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

    def seen_case_numbers(self) -> set[str]:
        rows = self.conn.execute("SELECT case_number FROM cases").fetchall()
        return {r[0] for r in rows}

    def upsert_case(self, case: "Case", status: str) -> None:
        self.conn.execute(
            """INSERT INTO cases(case_number, date_filed, tax_map_number, status)
                 VALUES(?, ?, ?, ?)
               ON CONFLICT(case_number) DO UPDATE SET
                 last_seen_at = CURRENT_TIMESTAMP,
                 tax_map_number = COALESCE(cases.tax_map_number, excluded.tax_map_number)""",
            (case.case_number, case.date_filed.isoformat(), case.tax_map_number, status),
        )

    def set_case_status(self, case_number: str, status: str) -> None:
        self.conn.execute(
            "UPDATE cases SET status=?, last_seen_at=CURRENT_TIMESTAMP WHERE case_number=?",
            (status, case_number),
        )

    def load_incomplete_cases(self) -> list["Case"]:
        rows = self.conn.execute(
            """SELECT case_number, date_filed, tax_map_number FROM cases
               WHERE status IN ('new','gis_done','error')"""
        ).fetchall()
        from datetime import date as _date
        return [
            Case(
                case_number=r[0],
                date_filed=_date.fromisoformat(r[1]),
                tax_map_number=r[2],
            )
            for r in rows
        ]

    def upsert_parcel(self, parcel: "Parcel") -> None:
        self.conn.execute(
            """INSERT INTO parcels(tax_map_number, owner_raw, site_street, site_city,
                                   site_state, site_zip)
                 VALUES(?,?,?,?,?,?)
               ON CONFLICT(tax_map_number) DO UPDATE SET
                 owner_raw=excluded.owner_raw,
                 site_street=excluded.site_street,
                 site_city=excluded.site_city,
                 site_state=excluded.site_state,
                 site_zip=excluded.site_zip,
                 resolved_at=CURRENT_TIMESTAMP""",
            (parcel.tax_map_number, parcel.owner_raw, parcel.site_street,
             parcel.site_city, parcel.site_state, parcel.site_zip),
        )

    def get_parcel(self, tax_map_number: str) -> "Parcel | None":
        row = self.conn.execute(
            """SELECT tax_map_number, owner_raw, site_street, site_city, site_state, site_zip
                 FROM parcels WHERE tax_map_number=?""",
            (tax_map_number,),
        ).fetchone()
        if not row:
            return None
        return Parcel(
            tax_map_number=row[0], owner_raw=row[1], site_street=row[2],
            site_city=row[3], site_state=row[4], site_zip=row[5],
        )

    def cache_skip_trace(self, person_key: str, owner_name: str,
                         street: str | None, city: str | None,
                         state: str | None, zip_: str | None,
                         mobiles: list[str]) -> None:
        self.conn.execute(
            """INSERT INTO skip_traces(person_key, owner_name, site_street, site_city,
                                       site_state, site_zip, mobiles_json)
                 VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(person_key) DO UPDATE SET
                 mobiles_json=excluded.mobiles_json,
                 traced_at=CURRENT_TIMESTAMP""",
            (person_key, owner_name, street, city, state, zip_, json.dumps(mobiles)),
        )

    def get_skip_trace(self, person_key: str) -> list[str] | None:
        row = self.conn.execute(
            "SELECT mobiles_json FROM skip_traces WHERE person_key=?",
            (person_key,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def record_sheet_row(self, case_number: str, person_key: str) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO sheet_rows(case_number, person_key) VALUES(?, ?)",
                (case_number, person_key),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def log_error(self, stage: str, case_number: str | None,
                  message: str, traceback: str) -> None:
        self.conn.execute(
            """INSERT INTO errors(stage, case_number, message, traceback)
                 VALUES(?,?,?,?)""",
            (stage, case_number, message, traceback),
        )

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO state(key, value) VALUES(?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM state WHERE key=?", (key,),
        ).fetchone()
        return row[0] if row else None

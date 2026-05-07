def test_init_schema_creates_all_tables(store):
    rows = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [r[0] for r in rows]
    assert "cases" in names
    assert "parcels" in names
    assert "skip_traces" in names
    assert "sheet_rows" in names
    assert "errors" in names
    assert "state" in names


def test_sheet_rows_unique_constraint(store):
    store.conn.execute(
        "INSERT INTO sheet_rows(case_number, person_key) VALUES('A','p1')"
    )
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO sheet_rows(case_number, person_key) VALUES('A','p1')"
        )


from datetime import date
from foreclosure_bot.models import Case


def test_seen_case_numbers_returns_set(store):
    store.conn.execute(
        "INSERT INTO cases(case_number, date_filed, status) VALUES('A','2024-01-01','new')"
    )
    store.conn.execute(
        "INSERT INTO cases(case_number, date_filed, status) VALUES('B','2024-01-02','completed')"
    )
    assert store.seen_case_numbers() == {"A", "B"}


def test_upsert_case_inserts(store):
    c = Case(case_number="X", date_filed=date(2024, 5, 1), tax_map_number="123")
    store.upsert_case(c, status="new")
    row = store.conn.execute(
        "SELECT case_number, tax_map_number, status FROM cases WHERE case_number='X'"
    ).fetchone()
    assert row == ("X", "123", "new")


def test_upsert_case_updates_last_seen_only(store):
    c = Case(case_number="X", date_filed=date(2024, 5, 1), tax_map_number="123")
    store.upsert_case(c, status="new")
    store.upsert_case(c, status="ignored_on_update")
    row = store.conn.execute(
        "SELECT status FROM cases WHERE case_number='X'"
    ).fetchone()
    assert row[0] == "new"


def test_set_case_status(store):
    c = Case(case_number="X", date_filed=date(2024, 5, 1))
    store.upsert_case(c, status="new")
    store.set_case_status("X", "completed")
    row = store.conn.execute("SELECT status FROM cases WHERE case_number='X'").fetchone()
    assert row[0] == "completed"


def test_load_incomplete_cases_returns_new_and_gis_done(store):
    store.conn.executemany(
        "INSERT INTO cases(case_number, date_filed, status) VALUES(?,?,?)",
        [
            ("A", "2024-01-01", "new"),
            ("B", "2024-01-02", "gis_done"),
            ("C", "2024-01-03", "completed"),
            ("D", "2024-01-04", "skipped_entity"),
            ("E", "2024-01-05", "error"),
        ],
    )
    nums = {c.case_number for c in store.load_incomplete_cases()}
    assert nums == {"A", "B", "E"}

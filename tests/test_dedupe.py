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


import json
from foreclosure_bot.models import Parcel


def test_parcel_upsert_and_get(store):
    p = Parcel(tax_map_number="T1", owner_raw="X", site_street="1 St",
               site_city="C", site_state="SC", site_zip="29461")
    store.upsert_parcel(p)
    got = store.get_parcel("T1")
    assert got.owner_raw == "X"
    assert got.site_zip == "29461"


def test_get_parcel_missing_returns_none(store):
    assert store.get_parcel("nope") is None


def test_skip_trace_cache(store):
    store.cache_skip_trace(
        person_key="smith|john||29461",
        owner_name="John Smith",
        street="1 St", city="C", state="SC", zip_="29461",
        mobiles=["8435551111"],
    )
    cached = store.get_skip_trace("smith|john||29461")
    assert cached == ["8435551111"]
    assert store.get_skip_trace("nope") is None


def test_skip_trace_cache_idempotent(store):
    for _ in range(2):
        store.cache_skip_trace(
            person_key="k", owner_name="n", street=None, city=None,
            state=None, zip_=None, mobiles=[],
        )
    count = store.conn.execute("SELECT COUNT(*) FROM skip_traces").fetchone()[0]
    assert count == 1


def test_record_sheet_row_first_call_returns_true(store):
    assert store.record_sheet_row("CASE1", "p1") is True


def test_record_sheet_row_second_call_returns_false(store):
    store.record_sheet_row("CASE1", "p1")
    assert store.record_sheet_row("CASE1", "p1") is False


def test_log_error(store):
    store.log_error(stage="court", case_number="X", message="boom", traceback="tb")
    row = store.conn.execute(
        "SELECT stage, case_number, message FROM errors"
    ).fetchone()
    assert row == ("court", "X", "boom")


def test_state_set_and_get(store):
    store.set_state("backfill_completed_at", "2024-05-01T00:00:00Z")
    assert store.get_state("backfill_completed_at") == "2024-05-01T00:00:00Z"
    assert store.get_state("missing") is None

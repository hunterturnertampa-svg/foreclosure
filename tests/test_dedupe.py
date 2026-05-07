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

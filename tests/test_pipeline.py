from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from foreclosure_bot.models import Case, Parcel, SheetRow
from foreclosure_bot.pipeline import Pipeline


@pytest.mark.asyncio
async def test_pipeline_writes_one_row_per_individual(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1),
                   tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="SMITH JOHN A & SMITH MARY B",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(side_effect=[
        ["8435551111"],
        ["8435552222", "8435553333"],
    ])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()

    assert tracerfy.skip_trace.await_count == 2
    assert sheets.append.await_count == 2
    rows = store.conn.execute("SELECT case_number, person_key FROM sheet_rows").fetchall()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_pipeline_dedupe_prevents_second_write(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1), tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="SMITH JOHN A",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(return_value=["8435551111"])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()
    await p.run()  # second run — should write nothing new

    assert sheets.append.await_count == 1


@pytest.mark.asyncio
async def test_pipeline_skips_entity_owner(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1), tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="ABC PROPERTIES LLC",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    sheets = MagicMock()

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()

    tracerfy.skip_trace.assert_not_called()
    status = store.conn.execute("SELECT status FROM cases WHERE case_number='C1'").fetchone()[0]
    assert status == "skipped_entity"


@pytest.mark.asyncio
async def test_pipeline_writes_row_with_no_mobiles(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1), tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="SMITH JOHN",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(return_value=[])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()

    sheets.append.assert_awaited_once()
    posted: SheetRow = sheets.append.await_args.args[0]
    assert posted.mobile_1 is None


@pytest.mark.asyncio
async def test_pipeline_backfill_cap_stops_skip_trace(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        for i in range(5):
            yield Case(case_number=f"C{i}", date_filed=date(2024, 5, 1),
                       tax_map_number=f"T{i}")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(side_effect=lambda tm: Parcel(
        tax_map_number=tm, owner_raw=f"SMITH PERSON{tm}",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(return_value=[])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=2,  # CAP
    )
    await p.run()

    assert tracerfy.skip_trace.await_count == 2
    incomplete = store.conn.execute(
        "SELECT COUNT(*) FROM cases WHERE status='gis_done'"
    ).fetchone()[0]
    assert incomplete == 3

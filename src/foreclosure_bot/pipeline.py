from datetime import date, datetime, timedelta, timezone
from .dedupe import Store
from .gis_lookup import GisClient, parse_owners
from .models import Case, Person, SheetRow
from .sheet_writer import SheetWriter
from .tracerfy import TracerfyClient


class Pipeline:
    def __init__(
        self,
        *,
        store: Store,
        scraper,
        gis: GisClient,
        tracerfy: TracerfyClient,
        sheets: SheetWriter,
        lookback_days: int,
        backfill_days: int,
        backfill_max_lookups: int,
    ):
        self.store = store
        self.scraper = scraper
        self.gis = gis
        self.tracerfy = tracerfy
        self.sheets = sheets
        self.lookback_days = lookback_days
        self.backfill_days = backfill_days
        self.backfill_max_lookups = backfill_max_lookups
        self._tracerfy_calls_this_run = 0

    async def run(self) -> None:
        # 1. Resume incomplete cases
        working: dict[str, Case] = {
            c.case_number: c for c in self.store.load_incomplete_cases()
        }

        # 2. Discover new cases
        is_backfill = self.store.get_state("backfill_completed_at") is None
        days = self.backfill_days if is_backfill else self.lookback_days
        end = date.today()
        start = end - timedelta(days=days)
        already_seen = self.store.seen_case_numbers()

        async for case in self.scraper.discover_cases(start, end, already_seen):
            status = "skipped_no_taxmap" if case.tax_map_number is None else "new"
            self.store.upsert_case(case, status=status)
            if case.tax_map_number:
                working[case.case_number] = case

        # 3-6. Process working set
        for case in list(working.values()):
            try:
                await self._process_case(case, is_backfill)
            except Exception as exc:
                import traceback
                self.store.log_error(
                    stage="pipeline", case_number=case.case_number,
                    message=str(exc), traceback=traceback.format_exc(),
                )
                self.store.set_case_status(case.case_number, "error")

        # Set backfill complete when no incomplete cases remain
        if is_backfill:
            remaining = self.store.conn.execute(
                "SELECT COUNT(*) FROM cases WHERE status IN ('new','gis_done','error')"
            ).fetchone()[0]
            if remaining == 0:
                self.store.set_state(
                    "backfill_completed_at",
                    datetime.now(timezone.utc).isoformat(),
                )

    async def _process_case(self, case: Case, is_backfill: bool) -> None:
        if case.tax_map_number is None:
            self.store.set_case_status(case.case_number, "skipped_no_taxmap")
            return

        # 3. GIS resolve
        parcel = self.store.get_parcel(case.tax_map_number)
        if parcel is None:
            parcel = await self.gis.query(case.tax_map_number)
            if parcel is None:
                self.store.set_case_status(case.case_number, "error")
                self.store.log_error(
                    stage="gis", case_number=case.case_number,
                    message="parcel not found", traceback="",
                )
                return
            self.store.upsert_parcel(parcel)
        self.store.set_case_status(case.case_number, "gis_done")

        # 4. Parse owners, drop entities
        owners = parse_owners(parcel.owner_raw)
        if not owners:
            self.store.set_case_status(case.case_number, "skipped_entity")
            return

        # 5-6. Skip trace + write
        all_written = True
        for owner in owners:
            person = Person(
                first=owner.first, middle=owner.middle, last=owner.last,
                zip_code=parcel.site_zip,
            )
            person_key = person.key()

            mobiles = self.store.get_skip_trace(person_key)
            if mobiles is None:
                if is_backfill and self._tracerfy_calls_this_run >= self.backfill_max_lookups:
                    all_written = False
                    continue
                mobiles = await self.tracerfy.skip_trace(
                    person,
                    street=parcel.site_street, city=parcel.site_city,
                    state=parcel.site_state, zip_=parcel.site_zip,
                )
                self._tracerfy_calls_this_run += 1
                self.store.cache_skip_trace(
                    person_key=person_key, owner_name=person.display_name(),
                    street=parcel.site_street, city=parcel.site_city,
                    state=parcel.site_state, zip_=parcel.site_zip,
                    mobiles=mobiles,
                )

            if not self.store.record_sheet_row(case.case_number, person_key):
                continue

            row = SheetRow(
                case_number=case.case_number, date_filed=case.date_filed,
                owner_name=person.display_name(),
                street=parcel.site_street or "", city=parcel.site_city or "",
                state=parcel.site_state or "SC", zip=parcel.site_zip or "",
                mobile_1=mobiles[0] if len(mobiles) > 0 else None,
                mobile_2=mobiles[1] if len(mobiles) > 1 else None,
                mobile_3=mobiles[2] if len(mobiles) > 2 else None,
            )
            ok = await self.sheets.append(row)
            if not ok:
                all_written = False
                self.store.log_error(
                    stage="sheet", case_number=case.case_number,
                    message="webhook returned non-ok", traceback="",
                )

        if all_written:
            self.store.set_case_status(case.case_number, "completed")

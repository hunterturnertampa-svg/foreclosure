import asyncio
import sys
import traceback

from .alerts import AlertSender
from .config import Settings
from .court_scraper import CourtScraper
from .dedupe import Store
from .gis_lookup import GisClient, GisFieldMap
from .pipeline import Pipeline
from .sheet_writer import SheetWriter
from .tracerfy import TracerfyClient


async def _run() -> int:
    settings = Settings()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(settings.sqlite_path)
    store.init_schema()
    alerts = AlertSender(
        store=store, host=settings.smtp_host, port=settings.smtp_port,
        user=settings.smtp_user, password=settings.smtp_pass,
        to=settings.alert_email_to,
    )
    try:
        scraper = CourtScraper(user_agent=settings.court_user_agent)
        gis = GisClient(
            query_url=settings.arcgis_parcel_query_url,
            fields=GisFieldMap(
                pin=settings.arcgis_parcel_pin_field,
                owner=settings.arcgis_parcel_owner_field,
                address=settings.arcgis_parcel_address_field,
                address_fallback=settings.arcgis_parcel_address_fallback_field,
                city=settings.arcgis_parcel_city_field,
                zip=settings.arcgis_parcel_zip_field,
            ),
        )
        tracerfy = TracerfyClient(api_key=settings.tracerfy_api_key)
        sheets = SheetWriter(
            url=settings.sheets_webhook_url, token=settings.sheets_webhook_token,
        )
        pipeline = Pipeline(
            store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
            sheets=sheets, alerts=alerts,
            lookback_days=settings.scrape_lookback_days,
            backfill_days=settings.backfill_days,
            backfill_max_lookups=settings.backfill_max_lookups,
        )
        await pipeline.run()
        return 0
    except Exception as exc:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        try:
            alerts.notify(stage="run", message=str(exc), traceback=tb)
        except Exception:
            pass
        return 1
    finally:
        store.close()


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()

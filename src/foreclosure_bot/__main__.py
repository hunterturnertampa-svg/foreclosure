import asyncio
import sys
import traceback

from .alerts import AlertSender
from .config import CountyConfig, Settings
from .court_scraper import CourtScraper
from .dedupe import Store
from .gis_lookup import GisClient, GisFieldMap
from .pipeline import Pipeline
from .sheet_writer import SheetWriter
from .tracerfy import TracerfyClient


def _make_gis(county: CountyConfig) -> GisClient:
    return GisClient(
        query_url=county.query_url,
        fields=GisFieldMap(
            pin=county.pin_field,
            owner=county.owner_field,
            address=county.address_field,
            address_fallback=county.address_fallback_field,
            city=county.city_field,
            zip=county.zip_field,
            csz=county.csz_field,
            pin_strip_dashes=county.pin_strip_dashes,
        ),
    )


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
    rc = 0
    try:
        tracerfy = TracerfyClient(api_key=settings.tracerfy_api_key)
        sheets = SheetWriter(
            url=settings.sheets_webhook_url, token=settings.sheets_webhook_token,
        )
        for county in settings.county_configs():
            try:
                scraper = CourtScraper(
                    user_agent=settings.court_user_agent, county=county.slug,
                )
                gis = _make_gis(county)
                pipeline = Pipeline(
                    store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
                    sheets=sheets, alerts=alerts,
                    lookback_days=settings.scrape_lookback_days,
                    backfill_days=settings.backfill_days,
                    backfill_max_lookups=settings.backfill_max_lookups,
                )
                await pipeline.run()
            except Exception as exc:
                tb = traceback.format_exc()
                print(f"[{county.slug}] {tb}", file=sys.stderr)
                store.log_error(
                    stage=f"county:{county.slug}",
                    case_number=None,
                    message=str(exc),
                    traceback=tb,
                )
                try:
                    alerts.notify(
                        stage=f"county:{county.slug}",
                        message=str(exc),
                        traceback=tb,
                    )
                except Exception:
                    pass
                rc = 1  # one county failed — keep going with the others
        return rc
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

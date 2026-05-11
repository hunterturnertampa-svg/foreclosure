import os
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_dotenv_into_environ() -> None:
    """pydantic-settings reads .env into the Settings instance but not into
    os.environ, so dynamically-prefixed vars like BERKELEY_ARCGIS_* would be
    invisible to our county_configs() lookups. Load them ourselves."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv_into_environ()


# SC court agency codes appear in case numbers as YYYYCP<code><sequence>.
# Authoritative list: https://www.sccourts.org/clerksDirectory/
_AGENCY_CODES = {
    "Berkeley": "08",
    "Charleston": "10",
    "Dorchester": "18",
}


def _default_agency_code(slug: str) -> str:
    if slug not in _AGENCY_CODES:
        raise ValueError(
            f"{slug}: no built-in agency code; set {slug.upper()}_ARCGIS_AGENCY_CODE"
        )
    return _AGENCY_CODES[slug]


class CountyConfig(BaseModel):
    """Per-county scraping + GIS configuration.

    Two GIS address shapes are supported:
    - Separate columns: set ``city_field`` and ``zip_field``.
    - Combined ``CITY_STATE_ZIP`` field (e.g. "BOWMAN SC 29018"): set ``csz_field``.
    Exactly one shape should be configured; if both, csz_field wins.
    """

    slug: str  # e.g. "Berkeley", "Dorchester" — used in the court URL path
    query_url: str
    pin_field: str
    owner_field: str
    address_field: str  # comma-separated for compound addresses (e.g. ST_NO,ST_NAME,ST_TYPE)
    address_fallback_field: str | None = None
    city_field: str | None = None
    zip_field: str | None = None
    csz_field: str | None = None
    pin_strip_dashes: bool = True
    # Optional per-county HTTP proxy (residential). Used for GIS only; the court
    # site is the same statewide host for all SC counties and never proxied.
    http_proxy: str | None = None
    # 2-digit SC court agency code embedded in case numbers (e.g. "08" Berkeley,
    # "10" Charleston, "18" Dorchester). Used to filter which incomplete cases
    # this county's pipeline retries.
    agency_code: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tracerfy_api_key: str
    sheets_webhook_url: str
    sheets_webhook_token: str

    alert_email_to: str
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str
    smtp_pass: str

    scrape_lookback_days: int = 7
    backfill_days: int = 30
    backfill_max_lookups: int = 200
    court_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    # Comma-separated list, processed in order each run.
    counties: str = "Berkeley"

    # Per-county vars are loaded dynamically below by ``county_configs()``.
    # We declare them lazily to avoid pydantic enumerating every possible slug.

    sqlite_path: Path = Path("data/bot.sqlite")

    def county_configs(self) -> list[CountyConfig]:
        configs: list[CountyConfig] = []
        for raw in self.counties.split(","):
            slug = raw.strip()
            if not slug:
                continue
            prefix = slug.upper() + "_ARCGIS_"

            def get(key: str, default: str | None = None) -> str | None:
                val = os.environ.get(prefix + key, default)
                return val if val else default

            query_url = get("QUERY_URL")
            if not query_url:
                raise ValueError(
                    f"{slug}: missing required env var {prefix}QUERY_URL"
                )
            configs.append(CountyConfig(
                slug=slug,
                query_url=query_url,
                pin_field=get("PIN_FIELD", "PIN"),
                owner_field=get("OWNER_FIELD", "OWNER"),
                address_field=get("ADDRESS_FIELD", "SITE_ADDRESS"),
                address_fallback_field=get("ADDRESS_FALLBACK_FIELD"),
                city_field=get("CITY_FIELD"),
                zip_field=get("ZIP_FIELD"),
                csz_field=get("CSZ_FIELD"),
                pin_strip_dashes=(get("PIN_STRIP_DASHES", "true") or "true").lower() == "true",
                http_proxy=get("HTTP_PROXY"),
                agency_code=get("AGENCY_CODE") or _default_agency_code(slug),
            ))
        if not configs:
            raise ValueError("at least one county must be configured")
        return configs

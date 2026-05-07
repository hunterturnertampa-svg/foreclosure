from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    arcgis_parcel_query_url: str
    arcgis_parcel_pin_field: str = "PIN"
    arcgis_parcel_owner_field: str = "OWNER"
    arcgis_parcel_address_field: str = "SITE_ADDRESS"
    arcgis_parcel_city_field: str = "SITE_CITY"
    arcgis_parcel_zip_field: str = "SITE_ZIP"

    sqlite_path: Path = Path("data/bot.sqlite")

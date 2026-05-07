import pytest

from foreclosure_bot.config import Settings


def test_settings_loads_required_fields(monkeypatch):
    monkeypatch.setenv("TRACERFY_API_KEY", "tk_test")
    monkeypatch.setenv("SHEETS_WEBHOOK_URL", "https://example.com/exec")
    monkeypatch.setenv("SHEETS_WEBHOOK_TOKEN", "tok")
    monkeypatch.setenv("ALERT_EMAIL_TO", "a@b.com")
    monkeypatch.setenv("SMTP_USER", "u@b.com")
    monkeypatch.setenv("SMTP_PASS", "p")
    monkeypatch.setenv("ARCGIS_PARCEL_QUERY_URL", "https://gis/query")

    s = Settings()

    assert s.tracerfy_api_key == "tk_test"
    assert s.scrape_lookback_days == 7  # default
    assert s.backfill_days == 30
    assert s.backfill_max_lookups == 200
    assert s.smtp_host == "smtp.gmail.com"


def test_settings_missing_required_raises(monkeypatch):
    for var in ["TRACERFY_API_KEY", "SHEETS_WEBHOOK_URL", "SHEETS_WEBHOOK_TOKEN",
                "ALERT_EMAIL_TO", "SMTP_USER", "SMTP_PASS", "ARCGIS_PARCEL_QUERY_URL"]:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValueError):
        Settings()

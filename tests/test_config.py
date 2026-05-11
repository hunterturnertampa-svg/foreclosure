import pytest

from foreclosure_bot.config import Settings


def _set_required(monkeypatch):
    monkeypatch.setenv("TRACERFY_API_KEY", "tk_test")
    monkeypatch.setenv("SHEETS_WEBHOOK_URL", "https://example.com/exec")
    monkeypatch.setenv("SHEETS_WEBHOOK_TOKEN", "tok")
    monkeypatch.setenv("ALERT_EMAIL_TO", "a@b.com")
    monkeypatch.setenv("SMTP_USER", "u@b.com")
    monkeypatch.setenv("SMTP_PASS", "p")


def test_settings_loads_required_fields(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("BERKELEY_ARCGIS_QUERY_URL", "https://gis/query")
    s = Settings()
    assert s.tracerfy_api_key == "tk_test"
    assert s.scrape_lookback_days == 7
    assert s.backfill_days == 30
    assert s.backfill_max_lookups == 200
    assert s.counties == "Berkeley"
    configs = s.county_configs()
    assert len(configs) == 1
    assert configs[0].slug == "Berkeley"


def test_settings_missing_required_raises(monkeypatch):
    for var in ["TRACERFY_API_KEY", "SHEETS_WEBHOOK_URL", "SHEETS_WEBHOOK_TOKEN",
                "ALERT_EMAIL_TO", "SMTP_USER", "SMTP_PASS"]:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValueError):
        Settings()


def test_county_configs_two_counties(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("COUNTIES", "Berkeley,Dorchester")
    monkeypatch.setenv("BERKELEY_ARCGIS_QUERY_URL", "https://b/query")
    monkeypatch.setenv("BERKELEY_ARCGIS_PIN_FIELD", "O_TMS")
    monkeypatch.setenv("BERKELEY_ARCGIS_CITY_FIELD", "City")
    monkeypatch.setenv("BERKELEY_ARCGIS_ZIP_FIELD", "Zip")
    monkeypatch.setenv("DORCHESTER_ARCGIS_QUERY_URL", "https://d/query")
    monkeypatch.setenv("DORCHESTER_ARCGIS_PIN_FIELD", "TMS")
    monkeypatch.setenv("DORCHESTER_ARCGIS_CSZ_FIELD", "CITY_STATE_ZIP")
    monkeypatch.setenv("DORCHESTER_ARCGIS_PIN_STRIP_DASHES", "false")

    s = Settings()
    configs = s.county_configs()
    assert [c.slug for c in configs] == ["Berkeley", "Dorchester"]
    assert configs[0].pin_field == "O_TMS"
    assert configs[0].csz_field is None
    assert configs[1].pin_field == "TMS"
    assert configs[1].csz_field == "CITY_STATE_ZIP"
    assert configs[1].pin_strip_dashes is False


def test_county_config_missing_query_url_raises(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("COUNTIES", "Berkeley")
    monkeypatch.delenv("BERKELEY_ARCGIS_QUERY_URL", raising=False)
    s = Settings()
    with pytest.raises(ValueError):
        s.county_configs()

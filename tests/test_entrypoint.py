import asyncio
from unittest.mock import patch

import pytest

from foreclosure_bot.__main__ import _run


def test_main_runs_without_unhandled_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACERFY_API_KEY", "tk")
    monkeypatch.setenv("SHEETS_WEBHOOK_URL", "https://example.com/exec")
    monkeypatch.setenv("SHEETS_WEBHOOK_TOKEN", "tok")
    monkeypatch.setenv("ALERT_EMAIL_TO", "t@x.com")
    monkeypatch.setenv("SMTP_USER", "u@x.com")
    monkeypatch.setenv("SMTP_PASS", "p")
    monkeypatch.setenv("ARCGIS_PARCEL_QUERY_URL", "https://gis.example.com/query")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "bot.sqlite"))

    async def empty_iter(start, end, seen):
        if False:
            yield

    with patch("foreclosure_bot.__main__.CourtScraper") as scraper_cls:
        scraper = scraper_cls.return_value
        scraper.discover_cases = empty_iter
        rc = asyncio.run(_run())
    assert rc == 0

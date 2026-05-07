from datetime import date

import httpx
import pytest
import respx

from foreclosure_bot.models import SheetRow
from foreclosure_bot.sheet_writer import SheetWriter


def make_row():
    return SheetRow(
        case_number="2024CP0801234", date_filed=date(2024, 5, 1),
        owner_name="John Smith", street="1 Main", city="C", state="SC", zip="29461",
        mobile_1="8435551111",
    )


@pytest.mark.asyncio
@respx.mock
async def test_append_posts_json_with_token():
    route = respx.post("https://script.google.com/exec").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    w = SheetWriter(url="https://script.google.com/exec", token="tok123")
    ok = await w.append(make_row())
    assert ok is True
    assert route.called
    body = route.calls.last.request.read().decode()
    assert "tok123" in body
    assert "2024CP0801234" in body


@pytest.mark.asyncio
@respx.mock
async def test_append_returns_false_on_non_200():
    respx.post("https://script.google.com/exec").mock(
        return_value=httpx.Response(500)
    )
    w = SheetWriter(url="https://script.google.com/exec", token="t")
    ok = await w.append(make_row())
    assert ok is False


@pytest.mark.asyncio
@respx.mock
async def test_append_returns_false_when_apps_script_reports_error():
    respx.post("https://script.google.com/exec").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "unauthorized"})
    )
    w = SheetWriter(url="https://script.google.com/exec", token="t")
    ok = await w.append(make_row())
    assert ok is False

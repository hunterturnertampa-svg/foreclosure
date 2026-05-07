import httpx
import pytest
import respx

from foreclosure_bot.models import Person
from foreclosure_bot.tracerfy import TracerfyClient


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_returns_mobiles_only():
    respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        return_value=httpx.Response(
            200,
            json={
                "phones": [
                    {"number": "8435551111", "type": "mobile"},
                    {"number": "8435552222", "type": "landline"},
                    {"number": "8435553333", "type": "mobile"},
                    {"number": "8435554444", "type": "voip"},
                ]
            },
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="John", last="Smith", zip_code="29461")
    mobiles = await c.skip_trace(person, street="1 St", city="C", state="SC", zip_="29461")
    assert mobiles == ["8435551111", "8435553333"]


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_truncates_to_three():
    respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        return_value=httpx.Response(
            200,
            json={"phones": [{"number": str(i)*10, "type": "mobile"} for i in range(5)]},
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="J", last="D")
    mobiles = await c.skip_trace(person, street=None, city=None, state=None, zip_=None)
    assert len(mobiles) == 3


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_retries_on_5xx():
    route = respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json={"phones": []}),
        ]
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="J", last="D")
    mobiles = await c.skip_trace(person, street=None, city=None, state=None, zip_=None)
    assert mobiles == []
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_gives_up_after_max_retries():
    respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        return_value=httpx.Response(503)
    )
    c = TracerfyClient(api_key="tk", max_retries=2)
    person = Person(first="J", last="D")
    with pytest.raises(httpx.HTTPStatusError):
        await c.skip_trace(person, street=None, city=None, state=None, zip_=None)

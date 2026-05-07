import httpx
import pytest
import respx

from foreclosure_bot.models import Person
from foreclosure_bot.tracerfy import TracerfyClient


URL = "https://tracerfy.com/v1/api/trace/lookup/"


def _hit(persons):
    return {
        "hit": True,
        "persons_count": len(persons),
        "credits_deducted": 5 * len(persons),
        "persons": persons,
    }


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_returns_mobiles_only():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_hit([{
                "first_name": "John", "last_name": "Smith",
                "phones": [
                    {"number": "8435551111", "type": "Mobile", "rank": 1},
                    {"number": "8435552222", "type": "Landline", "rank": 2},
                    {"number": "8435553333", "type": "Mobile", "rank": 3},
                ],
            }]),
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="John", last="Smith", zip_code="29461")
    mobiles = await c.skip_trace(person, street="1 St", city="C", state="SC", zip_="29461")
    assert mobiles == ["8435551111", "8435553333"]


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_returns_empty_on_miss():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200, json={"hit": False, "persons_count": 0, "credits_deducted": 0, "persons": []},
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="J", last="D")
    mobiles = await c.skip_trace(person, street="x", city="y", state="SC", zip_="29461")
    assert mobiles == []


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_truncates_to_three():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_hit([{
                "first_name": "J", "last_name": "D",
                "phones": [{"number": str(i)*10, "type": "Mobile", "rank": i} for i in range(5)],
            }]),
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="J", last="D")
    mobiles = await c.skip_trace(person, street="x", city="y", state="SC", zip_=None)
    assert len(mobiles) == 3


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_picks_matching_person_when_multiple_returned():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json=_hit([
                {"first_name": "Jane", "last_name": "Doe",
                 "phones": [{"number": "1111111111", "type": "Mobile", "rank": 1}]},
                {"first_name": "John", "last_name": "Smith",
                 "phones": [{"number": "2222222222", "type": "Mobile", "rank": 1}]},
            ]),
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="John", last="Smith")
    mobiles = await c.skip_trace(person, street="x", city="y", state="SC", zip_=None)
    assert mobiles == ["2222222222"]


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_retries_on_5xx():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json={"hit": False, "persons_count": 0,
                                      "credits_deducted": 0, "persons": []}),
        ]
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="J", last="D")
    mobiles = await c.skip_trace(person, street="x", city="y", state="SC", zip_=None)
    assert mobiles == []
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_gives_up_after_max_retries():
    respx.post(URL).mock(return_value=httpx.Response(503))
    c = TracerfyClient(api_key="tk", max_retries=2)
    person = Person(first="J", last="D")
    with pytest.raises(httpx.HTTPStatusError):
        await c.skip_trace(person, street="x", city="y", state="SC", zip_=None)

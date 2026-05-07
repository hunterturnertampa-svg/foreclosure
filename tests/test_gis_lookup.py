from foreclosure_bot.gis_lookup import OwnerName, is_entity, parse_owners


def test_is_entity_detects_llc():
    assert is_entity("ABC PROPERTIES LLC")
    assert is_entity("Some L.L.C.")
    assert is_entity("XYZ INC")
    assert is_entity("Acme TRUST")
    assert is_entity("THE ESTATE OF Mary Jones")
    assert is_entity("Wells Fargo BANK NA")


def test_is_entity_negatives():
    assert not is_entity("SMITH JOHN A")
    assert not is_entity("DOE JANE")


def test_parse_owners_single_individual():
    out = parse_owners("SMITH JOHN A")
    assert out == [OwnerName(first="JOHN", middle="A", last="SMITH")]


def test_parse_owners_no_middle():
    out = parse_owners("DOE JANE")
    assert out == [OwnerName(first="JANE", middle=None, last="DOE")]


def test_parse_owners_couple_ampersand():
    out = parse_owners("SMITH JOHN A & SMITH MARY B")
    assert out == [
        OwnerName(first="JOHN", middle="A", last="SMITH"),
        OwnerName(first="MARY", middle="B", last="SMITH"),
    ]


def test_parse_owners_couple_and():
    out = parse_owners("SMITH JOHN AND DOE MARY")
    assert len(out) == 2
    assert out[0].last == "SMITH"
    assert out[1].last == "DOE"


def test_parse_owners_couple_semicolon():
    out = parse_owners("SMITH JOHN; DOE JANE")
    assert len(out) == 2


def test_parse_owners_drops_entities():
    out = parse_owners("ABC LLC & SMITH JOHN")
    assert out == [OwnerName(first="JOHN", middle=None, last="SMITH")]


def test_parse_owners_all_entity_returns_empty():
    out = parse_owners("ABC LLC & XYZ TRUST")
    assert out == []


def test_parse_owners_empty_string():
    assert parse_owners("") == []
    assert parse_owners(None) == []


from pathlib import Path

import httpx
import pytest
import respx

from foreclosure_bot.gis_lookup import GisClient, GisFieldMap

FIXTURE = Path(__file__).parent / "fixtures" / "arcgis_response.json"


def fields():
    return GisFieldMap(pin="PIN", owner="OWNER", address="SITE_ADDRESS",
                      city="SITE_CITY", zip="SITE_ZIP")


@pytest.mark.asyncio
@respx.mock
async def test_query_returns_parcel():
    respx.get("https://gis.example.com/query").mock(
        return_value=httpx.Response(200, content=FIXTURE.read_bytes())
    )
    c = GisClient(query_url="https://gis.example.com/query", fields=fields())
    p = await c.query("123-45-67-001")
    assert p is not None
    assert p.owner_raw == "SMITH JOHN A & SMITH MARY B"
    assert p.site_street == "123 MAIN ST"
    assert p.site_city == "MONCKS CORNER"
    assert p.site_zip == "29461"
    assert p.site_state == "SC"


@pytest.mark.asyncio
@respx.mock
async def test_query_returns_none_when_no_features():
    respx.get("https://gis.example.com/query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )
    c = GisClient(query_url="https://gis.example.com/query", fields=fields())
    assert await c.query("nope") is None


@pytest.mark.asyncio
@respx.mock
async def test_query_uses_pin_field_in_where_clause():
    route = respx.get("https://gis.example.com/query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )
    c = GisClient(query_url="https://gis.example.com/query", fields=fields())
    await c.query("ABC")
    assert "PIN='ABC'" in route.calls.last.request.url.params["where"]

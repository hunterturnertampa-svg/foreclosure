from foreclosure_bot.gis_lookup import parse_owners, is_entity, OwnerName


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

from datetime import date

from foreclosure_bot.models import Case, Parcel, Person, SheetRow


def test_case_minimal():
    c = Case(case_number="2024CP0801234", date_filed=date(2024, 5, 1))
    assert c.tax_map_number is None


def test_parcel_with_address():
    p = Parcel(
        tax_map_number="123-45-67-001",
        owner_raw="SMITH JOHN A & SMITH MARY B",
        site_street="123 MAIN ST",
        site_city="MONCKS CORNER",
        site_state="SC",
        site_zip="29461",
    )
    assert p.site_state == "SC"


def test_person_key_normalization():
    p = Person(first="John", middle="A", last="Smith", zip_code="29461")
    assert p.key() == "smith|john|a|29461"


def test_person_key_handles_missing_middle_and_zip():
    p = Person(first="JANE", middle=None, last="DOE", zip_code=None)
    assert p.key() == "doe|jane||"


def test_sheet_row_round_trip():
    r = SheetRow(
        case_number="X", date_filed=date(2024, 1, 1),
        first_name="John", last_name="Smith",
        street="1 St", city="C", state="SC", zip="29461",
        mobile_1="8435551111", mobile_2=None, mobile_3=None,
    )
    d = r.model_dump(mode="json")
    assert d["first_name"] == "John"
    assert d["last_name"] == "Smith"
    assert d["mobile_2"] is None
    assert d["date_filed"] == "2024-01-01"

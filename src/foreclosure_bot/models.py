from datetime import date

from pydantic import BaseModel


class Case(BaseModel):
    case_number: str
    date_filed: date
    tax_map_number: str | None = None


class Parcel(BaseModel):
    tax_map_number: str
    owner_raw: str | None = None
    site_street: str | None = None
    site_city: str | None = None
    site_state: str | None = "SC"
    site_zip: str | None = None


class Person(BaseModel):
    first: str
    middle: str | None = None
    last: str
    zip_code: str | None = None

    def key(self) -> str:
        parts = [self.last, self.first, self.middle or "", self.zip_code or ""]
        return "|".join(p.lower().strip() for p in parts)

    def display_name(self) -> str:
        bits = [self.first, self.middle, self.last]
        return " ".join(b for b in bits if b)


class SkipTraceResult(BaseModel):
    person_key: str
    mobiles: list[str]


class SheetRow(BaseModel):
    case_number: str
    date_filed: date
    owner_name: str
    street: str
    city: str
    state: str
    zip: str
    mobile_1: str | None = None
    mobile_2: str | None = None
    mobile_3: str | None = None

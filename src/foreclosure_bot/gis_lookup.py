import re
from dataclasses import dataclass

import httpx

from .models import Parcel

_ENTITY_TOKENS = {
    "LLC", "L.L.C.", "L.L.C", "INC", "INC.", "INCORPORATED",
    "CORP", "CORP.", "CORPORATION",
    "LTD", "LTD.", "LIMITED",
    "TRUST", "TRUSTEE", "TRUSTEES",
    "BANK", "LP", "L.P.", "LLP", "L.L.P.",
}
_ENTITY_PHRASES = ("ESTATE OF",)


def is_entity(name: str) -> bool:
    if not name:
        return False
    upper = name.upper()
    for phrase in _ENTITY_PHRASES:
        if phrase in upper:
            return True
    tokens = set(re.split(r"[\s,]+", upper))
    return bool(tokens & _ENTITY_TOKENS)


@dataclass(frozen=True)
class OwnerName:
    first: str
    middle: str | None
    last: str


_SPLIT_RE = re.compile(r"\s*(?:&|;|\bAND\b)\s*", re.IGNORECASE)


def parse_owners(raw: str | None) -> list[OwnerName]:
    if not raw:
        return []
    out: list[OwnerName] = []
    for fragment in _SPLIT_RE.split(raw):
        fragment = fragment.strip()
        if not fragment or is_entity(fragment):
            continue
        parts = fragment.split()
        if len(parts) < 2:
            continue
        last = parts[0]
        first = parts[1]
        middle = parts[2] if len(parts) >= 3 else None
        out.append(OwnerName(first=first, middle=middle, last=last))
    return out


@dataclass(frozen=True)
class GisFieldMap:
    pin: str
    owner: str
    address: str
    address_fallback: str | None = None
    city: str | None = None  # mutually exclusive with csz
    zip: str | None = None
    csz: str | None = None   # combined "CITY STATE ZIP" field (Dorchester-style)
    pin_strip_dashes: bool = True


def normalize_tms(raw: str, strip_dashes: bool = True) -> str:
    """Berkeley stores parcels with digits only ("0120000058"); Dorchester
    keeps the dashed format ("003-00-00-037"). The court site shows the
    dashed format in both cases, so we strip when the GIS column is digits-only.
    """
    s = raw or ""
    if strip_dashes:
        return re.sub(r"[^A-Za-z0-9]", "", s)
    return s.strip()


_CSZ_RE = re.compile(r"^\s*(.+?)\s+([A-Z]{2})\s+(\d{5,9})\s*$")


def parse_csz(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """Parse 'BOWMAN SC 29018' or 'MONCKS CORNER SC 294619462' → (city, state, zip5)."""
    if not raw:
        return None, None, None
    m = _CSZ_RE.match(raw.strip())
    if not m:
        return None, None, None
    city, state, zip_raw = m.groups()
    zip5 = zip_raw[:5] if zip_raw else None
    return city.strip(), state, zip5


class GisClient:
    def __init__(self, query_url: str, fields: GisFieldMap, timeout: float = 30.0):
        self.query_url = query_url
        self.fields = fields
        self.timeout = timeout

    async def query(self, tax_map_number: str) -> Parcel | None:
        normalized = normalize_tms(tax_map_number, self.fields.pin_strip_dashes)
        safe_pin = normalized.replace("'", "''")
        out_fields = [self.fields.owner, self.fields.address]
        for extra in (self.fields.address_fallback, self.fields.city,
                      self.fields.zip, self.fields.csz):
            if extra:
                out_fields.append(extra)
        params = {
            "where": f"{self.fields.pin}='{safe_pin}'",
            "outFields": ",".join(out_fields),
            "returnGeometry": "false",
            "f": "json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(self.query_url, params=params)
            resp.raise_for_status()
            data = resp.json()
        features = data.get("features") or []
        if not features:
            return None
        attrs = features[0].get("attributes", {})

        street = (attrs.get(self.fields.address) or "").strip()
        if not street and self.fields.address_fallback:
            street = (attrs.get(self.fields.address_fallback) or "").strip()

        if self.fields.csz:
            city, _state, zip5 = parse_csz(attrs.get(self.fields.csz))
        else:
            city = attrs.get(self.fields.city) if self.fields.city else None
            zip_raw = str(attrs.get(self.fields.zip) or "") if self.fields.zip else ""
            zip5 = zip_raw.split("-")[0].strip() or None

        return Parcel(
            tax_map_number=tax_map_number,
            owner_raw=attrs.get(self.fields.owner),
            site_street=street or None,
            site_city=city,
            site_state="SC",
            site_zip=zip5 or None,
        )

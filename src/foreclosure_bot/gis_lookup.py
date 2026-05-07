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
    city: str
    zip: str
    address_fallback: str | None = None


def normalize_tms(raw: str) -> str:
    """Strip dashes, spaces, and dots — Berkeley's O_TMS field stores digits only."""
    return re.sub(r"[^A-Za-z0-9]", "", raw or "")


class GisClient:
    def __init__(self, query_url: str, fields: GisFieldMap, timeout: float = 30.0):
        self.query_url = query_url
        self.fields = fields
        self.timeout = timeout

    async def query(self, tax_map_number: str) -> Parcel | None:
        normalized = normalize_tms(tax_map_number)
        safe_pin = normalized.replace("'", "''")
        out_fields = [self.fields.owner, self.fields.address,
                      self.fields.city, self.fields.zip]
        if self.fields.address_fallback:
            out_fields.append(self.fields.address_fallback)
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
        street = attrs.get(self.fields.address) or ""
        if not street.strip() and self.fields.address_fallback:
            street = (attrs.get(self.fields.address_fallback) or "").strip()
        zip_raw = str(attrs.get(self.fields.zip) or "")
        zip5 = zip_raw.split("-")[0].strip()
        return Parcel(
            tax_map_number=tax_map_number,
            owner_raw=attrs.get(self.fields.owner),
            site_street=(street or "").strip() or None,
            site_city=attrs.get(self.fields.city),
            site_state="SC",
            site_zip=zip5 or None,
        )

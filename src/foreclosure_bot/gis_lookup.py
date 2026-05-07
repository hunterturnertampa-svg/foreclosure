import re
from dataclasses import dataclass


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

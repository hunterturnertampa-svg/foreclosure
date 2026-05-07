import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import Person


class TracerfyClient:
    URL = "https://tracerfy.com/v1/api/trace/lookup/"

    def __init__(self, api_key: str, max_retries: int = 3, timeout: float = 30.0):
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout

    async def skip_trace(self, person: Person, *, street: str | None,
                         city: str | None, state: str | None,
                         zip_: str | None) -> list[str]:
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TransportError)),
            reraise=True,
        )
        async def _call() -> list[str]:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "first_name": person.first,
                        "last_name": person.last,
                        "address": street or "",
                        "city": city or "",
                        "state": state or "SC",
                        "zip": zip_ or "",
                        "find_owner": False,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return self._parse_response(data, person)
        return await _call()

    @staticmethod
    def _parse_response(data: dict, target: Person) -> list[str]:
        if not data.get("hit"):
            return []
        persons = data.get("persons") or []
        # Match the person Tracerfy returned to the one we asked about (by last/first name).
        # If multiple persons returned, prefer one whose last+first matches; otherwise use first.
        chosen = None
        target_last = target.last.lower().strip()
        target_first = target.first.lower().strip()
        for p in persons:
            if (p.get("last_name", "").lower().strip() == target_last and
                p.get("first_name", "").lower().strip() == target_first):
                chosen = p
                break
        if chosen is None and persons:
            chosen = persons[0]
        if chosen is None:
            return []
        phones = chosen.get("phones") or []
        mobiles = [str(p["number"]) for p in phones if p.get("type") == "Mobile"]
        return mobiles[:3]

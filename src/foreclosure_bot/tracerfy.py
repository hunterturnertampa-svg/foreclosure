import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import Person


class TracerfyClient:
    BASE = "https://api.tracerfy.com/v1"

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
                    f"{self.BASE}/skip-trace",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "first_name": person.first,
                        "middle_name": person.middle,
                        "last_name": person.last,
                        "street": street,
                        "city": city,
                        "state": state,
                        "zip": zip_,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            return self._parse_response(data)
        return await _call()

    @staticmethod
    def _parse_response(data: dict) -> list[str]:
        phones = data.get("phones", [])
        mobiles = [p["number"] for p in phones if p.get("type") == "mobile"]
        return mobiles[:3]

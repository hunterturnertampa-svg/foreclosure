import httpx
from .models import SheetRow


class SheetWriter:
    def __init__(self, url: str, token: str, timeout: float = 20.0):
        self.url = url
        self.token = token
        self.timeout = timeout

    async def append(self, row: SheetRow) -> bool:
        payload = row.model_dump(mode="json")
        payload["token"] = self.token
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.url, json=payload)
                if resp.status_code != 200:
                    return False
                data = resp.json()
                return bool(data.get("ok"))
        except httpx.HTTPError:
            return False

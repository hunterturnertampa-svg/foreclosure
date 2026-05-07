import asyncio
import random
import re
from collections.abc import AsyncIterator
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.async_api import Page, async_playwright

from .models import Case


def parse_search_results(html: str) -> list[Case]:
    soup = BeautifulSoup(html, "lxml")
    cases: list[Case] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a")
        if not link:
            continue
        case_number = link.get_text(strip=True)
        date_str = cells[1].get_text(strip=True)
        try:
            d = datetime.strptime(date_str, "%m/%d/%Y").date()
        except ValueError:
            continue
        cases.append(Case(case_number=case_number, date_filed=d))
    return cases


_TAX_MAP_LABEL = re.compile(r"tax\s*map", re.IGNORECASE)


def parse_case_detail(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        if _TAX_MAP_LABEL.search(label):
            value = cells[1].get_text(strip=True)
            return value or None
    return None


COURT_URL = "https://publicindex.sccourts.org/Berkeley/PublicIndex/PISearch.aspx"


class CourtScraperError(RuntimeError):
    """Raised when the site returns a CAPTCHA, 403, or repeated 5xx — abort the run."""


class CourtScraper:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    async def discover_cases(
        self,
        start_date: date,
        end_date: date,
        already_seen: set[str],
    ) -> AsyncIterator[Case]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()
            try:
                await self._accept_disclaimer(page)
                await self._submit_search(page, start_date, end_date)
                async for case in self._iter_results(page, already_seen):
                    yield case
            finally:
                await context.close()
                await browser.close()

    async def _accept_disclaimer(self, page: Page) -> None:
        await page.goto(COURT_URL, wait_until="domcontentloaded")
        agree = page.locator("input[value*='agree' i], button:has-text('agree' i)")
        if await agree.count() > 0:
            await agree.first.click()
            await page.wait_for_load_state("domcontentloaded")
        if await page.locator("img[src*='captcha' i]").count() > 0:
            raise CourtScraperError("CAPTCHA detected")

    async def _submit_search(self, page: Page, start: date, end: date) -> None:
        await page.select_option("select[id*='CaseType' i]", label="Common Pleas")
        await page.select_option("select[id*='SubType' i]", label="Foreclosure 420")
        await page.select_option("select[id*='DateType' i]", label="Date Case Filed")
        await page.fill("input[id*='StartDate' i]", start.strftime("%m/%d/%Y"))
        await page.fill("input[id*='EndDate' i]", end.strftime("%m/%d/%Y"))
        await page.click("input[id*='SearchButton' i], button:has-text('Search')")
        await page.wait_for_load_state("networkidle")

    async def _iter_results(
        self, page: Page, already_seen: set[str]
    ) -> AsyncIterator[Case]:
        while True:
            html = await page.content()
            for shallow in parse_search_results(html):
                if shallow.case_number in already_seen:
                    continue
                tax_map = await self._open_detail(page, shallow.case_number)
                yield Case(
                    case_number=shallow.case_number,
                    date_filed=shallow.date_filed,
                    tax_map_number=tax_map,
                )
                await page.go_back(wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2.0, 4.0))
            next_btn = page.locator("a:has-text('Next')")
            if await next_btn.count() == 0 or not await next_btn.first.is_enabled():
                break
            await next_btn.first.click()
            await page.wait_for_load_state("networkidle")

    async def _open_detail(self, page: Page, case_number: str) -> str | None:
        link = page.locator(f"a:has-text('{case_number}')").first
        await link.click()
        await page.wait_for_load_state("domcontentloaded")
        html = await page.content()
        return parse_case_detail(html)

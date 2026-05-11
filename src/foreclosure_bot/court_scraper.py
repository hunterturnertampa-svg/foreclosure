import asyncio
import random
import re
from collections.abc import AsyncIterator
from datetime import date, datetime

from bs4 import BeautifulSoup
from patchright.async_api import Page, async_playwright

from .models import Case


COURT_URL = "https://publicindex.sccourts.org/Berkeley/PublicIndex/PISearch.aspx"

# Form field IDs (verified live against publicindex.sccourts.org)
SEL_CASE_TYPE = "#ContentPlaceHolder1_DropDownListCaseTypes"
SEL_SUB_TYPE = "#ContentPlaceHolder1_DropdownlistCaseSubType"
SEL_DATE_FILTER = "#ContentPlaceHolder1_DropDownListDateFilter"
SEL_DATE_FROM = "#ContentPlaceHolder1_TextBoxDateFrom"
SEL_DATE_TO = "#ContentPlaceHolder1_TextBoxDateTo"
SEL_SEARCH_BUTTON = "#ContentPlaceHolder1_ButtonSearch"
SEL_RESULTS_TABLE = "#ContentPlaceHolder1_SearchResults"

CASE_TYPE_VALUE = "CP  "  # ASP.NET pads with trailing spaces
SUB_TYPE_LABEL = "Foreclosure 420"
DATE_FILTER_VALUE = "Filed"


class CourtScraperError(RuntimeError):
    """Raised when the site returns a CAPTCHA, 403, or repeated 5xx — abort the run."""


def parse_search_results(html: str) -> list[Case]:
    """Parse the SearchResults grid. Live cell layout:
    [0]=plaintiff label, [1]=defendant label, [2]=case number link,
    [3]=date filed, [4]=status, [5]=disposition date, [6]=type,
    [7]=subtype, [8]=judgment, [9]=court agency.
    Falls back to legacy two-cell format used by offline test fixtures.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="ContentPlaceHolder1_SearchResults")
    if table is None:
        table = soup.find("table")
    if table is None:
        return []
    cases: list[Case] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        if len(cells) >= 4 and cells[2].find("a"):
            case_number = cells[2].find("a").get_text(strip=True)
            date_str = cells[3].get_text(strip=True)
        else:
            link = cells[0].find("a")
            if not link:
                continue
            case_number = link.get_text(strip=True)
            date_str = cells[1].get_text(strip=True)
        if not case_number:
            continue
        try:
            d = datetime.strptime(date_str, "%m/%d/%Y").date()
        except ValueError:
            continue
        cases.append(Case(case_number=case_number, date_filed=d))
    return cases


_TAX_MAP_LABEL = re.compile(r"tax\s*map\s*number", re.IGNORECASE)
_TAX_MAP_LABEL_LOOSE = re.compile(r"tax\s*map", re.IGNORECASE)


def parse_case_detail(html: str) -> str | None:
    """Find the Tax Map Number on the case detail page.

    Live structure: a table whose header row contains "Tax Map Number" — we
    return the first non-empty value from the matching column. Falls back to
    the legacy label/value-in-adjacent-cells format for offline test fixtures.
    """
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        headers = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        tms_idx = next((i for i, h in enumerate(headers)
                        if _TAX_MAP_LABEL.search(h)), None)
        if tms_idx is None:
            continue
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) > tms_idx:
                val = cells[tms_idx].get_text(strip=True)
                if val:
                    return val
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        if _TAX_MAP_LABEL_LOOSE.search(cells[0].get_text(strip=True)):
            value = cells[1].get_text(strip=True)
            return value or None
    return None


class CourtScraper:
    def __init__(self, user_agent: str):
        # Kept for compatibility; real Chrome (channel='chrome') sets its own UA.
        self.user_agent = user_agent

    async def discover_cases(
        self,
        start_date: date,
        end_date: date,
        already_seen: set[str],
    ) -> AsyncIterator[Case]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, channel="chrome")
            context = await browser.new_context()
            page = await context.new_page()
            try:
                await page.goto(COURT_URL, wait_until="domcontentloaded")
                await asyncio.sleep(3)
                if "Public Index Search" not in (await page.title()):
                    raise CourtScraperError(
                        f"unexpected landing page: {await page.title()!r}"
                    )
                await self._submit_search(page, start_date, end_date)
                async for case in self._iter_results(page, already_seen):
                    yield case
            finally:
                await context.close()
                await browser.close()

    async def _submit_search(self, page: Page, start: date, end: date) -> None:
        await page.select_option(SEL_CASE_TYPE, value=CASE_TYPE_VALUE)
        await asyncio.sleep(4)
        await page.select_option(SEL_SUB_TYPE, label=SUB_TYPE_LABEL)
        await asyncio.sleep(2)
        await page.select_option(SEL_DATE_FILTER, value=DATE_FILTER_VALUE)
        await page.fill(SEL_DATE_FROM, start.strftime("%m/%d/%Y"))
        await page.fill(SEL_DATE_TO, end.strftime("%m/%d/%Y"))
        await page.click(SEL_SEARCH_BUTTON)
        await asyncio.sleep(8)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass

    async def _iter_results(
        self, page: Page, already_seen: set[str]
    ) -> AsyncIterator[Case]:
        html = await page.content()
        all_cases = parse_search_results(html)
        new_cases = [c for c in all_cases if c.case_number not in already_seen]
        for shallow in new_cases:
            try:
                tax_map = await self._open_detail_for_case(page, shallow.case_number)
            except Exception:
                tax_map = None
            yield Case(
                case_number=shallow.case_number,
                date_filed=shallow.date_filed,
                tax_map_number=tax_map,
            )
            await asyncio.sleep(random.uniform(2.0, 4.0))

    async def _open_detail_for_case(
        self, page: Page, case_number: str
    ) -> str | None:
        link = page.locator(f"{SEL_RESULTS_TABLE} a", has_text=case_number).first
        await link.click()
        await asyncio.sleep(5)
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        html = await page.content()
        tms = parse_case_detail(html)
        await page.go_back(wait_until="domcontentloaded")
        await asyncio.sleep(2)
        return tms

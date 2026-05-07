import re
from datetime import date, datetime
from bs4 import BeautifulSoup
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

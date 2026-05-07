from datetime import date
from pathlib import Path
from foreclosure_bot.court_scraper import (
    parse_search_results,
    parse_case_detail,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_search_results_returns_two_cases():
    html = (FIXTURES / "court_search_results.html").read_text()
    cases = parse_search_results(html)
    assert len(cases) == 2
    assert cases[0].case_number == "2024CP0801234"
    assert cases[0].date_filed == date(2024, 5, 1)
    assert cases[1].case_number == "2024CP0805678"


def test_parse_case_detail_extracts_tax_map():
    html = (FIXTURES / "court_case_detail.html").read_text()
    tax_map = parse_case_detail(html)
    assert tax_map == "123-45-67-001"


def test_parse_case_detail_returns_none_when_missing():
    html = "<html><body><p>nothing here</p></body></html>"
    assert parse_case_detail(html) is None

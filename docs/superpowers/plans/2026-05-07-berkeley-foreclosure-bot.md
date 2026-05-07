# Berkeley Foreclosure Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained Python bot that scrapes Berkeley County SC foreclosure filings hourly, enriches each parcel with owner info from ArcGIS and mobile numbers from Tracerfy, and appends de-duplicated rows to a Google Sheet.

**Architecture:** Single Python 3.12 package run by a systemd timer on a small Ubuntu VPS. Playwright drives the ASP.NET court site; httpx handles ArcGIS, Tracerfy, and the Apps Script webhook. SQLite holds dedupe state with a four-level UNIQUE constraint hierarchy that makes duplicate sheet rows impossible.

**Tech Stack:** Python 3.12, uv (deps), Playwright (Chromium), httpx, pydantic-settings, pytest + respx (HTTP mocking), SQLite (stdlib), systemd, smtplib (stdlib), Google Apps Script (sink).

**Spec:** [docs/superpowers/specs/2026-05-07-berkeley-foreclosure-bot-design.md](../specs/2026-05-07-berkeley-foreclosure-bot-design.md)

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv-managed deps, package metadata, pytest config |
| `.env.example` | Documented env-var template |
| `.gitignore` | Exclude `.env`, `data/`, `__pycache__`, `.venv` |
| `README.md` | One-page operator guide |
| `src/foreclosure_bot/__main__.py` | Entrypoint, top-level exception → email alert |
| `src/foreclosure_bot/config.py` | Pydantic settings model (loads `.env`) |
| `src/foreclosure_bot/dedupe.py` | SQLite schema, person_key, all CRUD against state DB |
| `src/foreclosure_bot/tracerfy.py` | Tracerfy API client (httpx) |
| `src/foreclosure_bot/sheet_writer.py` | POST to Apps Script webhook |
| `src/foreclosure_bot/gis_lookup.py` | ArcGIS REST query + owner-string parser + entity filter |
| `src/foreclosure_bot/court_scraper.py` | Playwright driver for PublicIndex |
| `src/foreclosure_bot/alerts.py` | SMTP send + throttle |
| `src/foreclosure_bot/pipeline.py` | Orchestrator (the per-run pipeline from spec §4) |
| `src/foreclosure_bot/models.py` | Pydantic dataclasses: `Case`, `Parcel`, `Person`, `SkipTraceResult`, `SheetRow` |
| `tests/conftest.py` | Pytest fixtures: in-memory SQLite, fake settings, respx routers |
| `tests/test_dedupe.py` | Schema + helpers + person_key normalization |
| `tests/test_tracerfy.py` | Mocked API responses |
| `tests/test_sheet_writer.py` | Mocked webhook |
| `tests/test_gis_lookup.py` | Mocked ArcGIS + parser unit tests |
| `tests/test_court_scraper.py` | Offline fixture HTML + parser tests |
| `tests/test_alerts.py` | SMTP mock + throttle behavior |
| `tests/test_pipeline.py` | End-to-end orchestration with all I/O mocked |
| `tests/fixtures/court_search_results.html` | Saved page for offline scraper tests |
| `tests/fixtures/court_case_detail.html` | Saved page for offline scraper tests |
| `tests/fixtures/arcgis_response.json` | Saved ArcGIS REST response |
| `deploy/foreclosure-bot.service` | systemd oneshot |
| `deploy/foreclosure-bot.timer` | systemd timer (hourly) |
| `deploy/setup.sh` | One-shot VPS provisioning |
| `deploy/backup.sh` | Nightly SQLite backup |
| `deploy/apps_script.gs` | Google Apps Script the user pastes into their Sheet |

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`
- Create: `src/foreclosure_bot/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "foreclosure-bot"
version = "0.1.0"
description = "Berkeley County SC foreclosure scraper + skip trace"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.27",
    "playwright>=1.45",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "tenacity>=9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
    "ruff>=0.5",
    "mypy>=1.10",
]

[project.scripts]
foreclosure-bot = "foreclosure_bot.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --strict-markers"
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "RUF"]
```

- [ ] **Step 2: Create `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.env
data/
*.sqlite
*.sqlite-journal
/tmp/
node_modules/
.playwright/
```

- [ ] **Step 3: Create `.env.example`**

```env
# Tracerfy
TRACERFY_API_KEY=

# Google Sheets webhook
SHEETS_WEBHOOK_URL=
SHEETS_WEBHOOK_TOKEN=

# Email alerts (Gmail App Password recommended)
ALERT_EMAIL_TO=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=

# Behavior
SCRAPE_LOOKBACK_DAYS=7
BACKFILL_DAYS=30
BACKFILL_MAX_LOOKUPS=200
COURT_USER_AGENT=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36

# ArcGIS layer URL (discovered at deploy time — see README)
ARCGIS_PARCEL_QUERY_URL=
ARCGIS_PARCEL_PIN_FIELD=PIN
ARCGIS_PARCEL_OWNER_FIELD=OWNER
ARCGIS_PARCEL_ADDRESS_FIELD=SITE_ADDRESS
ARCGIS_PARCEL_CITY_FIELD=SITE_CITY
ARCGIS_PARCEL_ZIP_FIELD=SITE_ZIP

# Storage
SQLITE_PATH=data/bot.sqlite
```

- [ ] **Step 4: Create `README.md`**

```markdown
# foreclosure-bot

Berkeley County SC foreclosure lead bot. See `docs/superpowers/specs/` for design.

## Local development

    uv venv && uv pip install -e ".[dev]"
    uv run playwright install chromium
    cp .env.example .env  # then fill it in
    uv run pytest
    uv run python -m foreclosure_bot

## Deploy to VPS

See `deploy/setup.sh`.

## Configuring ArcGIS

The Berkeley County GIS service URL must be discovered once at deploy time:

1. Visit `https://gis.berkeleycountysc.gov/arcgis/rest/services` in a browser.
2. Find the parcel layer (commonly under a "Parcels" or "Tax" folder).
3. Note the layer URL ending in `/MapServer/N`. Set `ARCGIS_PARCEL_QUERY_URL=<that_url>/query`.
4. Append `?f=json` to the layer URL to view its fields. Update the `ARCGIS_PARCEL_*_FIELD` env vars to match.
```

- [ ] **Step 5: Create empty package files**

```python
# src/foreclosure_bot/__init__.py
"""Berkeley County SC foreclosure lead bot."""
```

```python
# tests/__init__.py
```

- [ ] **Step 6: Verify install works**

```bash
uv venv
uv pip install -e ".[dev]"
uv run pytest --collect-only
```

Expected: pytest collects 0 tests, no import errors.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore .env.example README.md src/ tests/
git commit -m "scaffold: project layout, deps, env template"
```

---

### Task 2: Config loader

**Files:**
- Create: `src/foreclosure_bot/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import pytest
from foreclosure_bot.config import Settings


def test_settings_loads_required_fields(monkeypatch):
    monkeypatch.setenv("TRACERFY_API_KEY", "tk_test")
    monkeypatch.setenv("SHEETS_WEBHOOK_URL", "https://example.com/exec")
    monkeypatch.setenv("SHEETS_WEBHOOK_TOKEN", "tok")
    monkeypatch.setenv("ALERT_EMAIL_TO", "a@b.com")
    monkeypatch.setenv("SMTP_USER", "u@b.com")
    monkeypatch.setenv("SMTP_PASS", "p")
    monkeypatch.setenv("ARCGIS_PARCEL_QUERY_URL", "https://gis/query")

    s = Settings()

    assert s.tracerfy_api_key == "tk_test"
    assert s.scrape_lookback_days == 7  # default
    assert s.backfill_days == 30
    assert s.backfill_max_lookups == 200
    assert s.smtp_host == "smtp.gmail.com"


def test_settings_missing_required_raises(monkeypatch):
    for var in ["TRACERFY_API_KEY", "SHEETS_WEBHOOK_URL", "SHEETS_WEBHOOK_TOKEN",
                "ALERT_EMAIL_TO", "SMTP_USER", "SMTP_PASS", "ARCGIS_PARCEL_QUERY_URL"]:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(Exception):
        Settings()
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: ImportError or ModuleNotFoundError on `Settings`.

- [ ] **Step 3: Implement `config.py`**

```python
# src/foreclosure_bot/config.py
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tracerfy_api_key: str
    sheets_webhook_url: str
    sheets_webhook_token: str

    alert_email_to: str
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str
    smtp_pass: str

    scrape_lookback_days: int = 7
    backfill_days: int = 30
    backfill_max_lookups: int = 200
    court_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    arcgis_parcel_query_url: str
    arcgis_parcel_pin_field: str = "PIN"
    arcgis_parcel_owner_field: str = "OWNER"
    arcgis_parcel_address_field: str = "SITE_ADDRESS"
    arcgis_parcel_city_field: str = "SITE_CITY"
    arcgis_parcel_zip_field: str = "SITE_ZIP"

    sqlite_path: Path = Path("data/bot.sqlite")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/config.py tests/test_config.py
git commit -m "feat(config): pydantic settings model with .env loading"
```

---

### Task 3: Domain models

**Files:**
- Create: `src/foreclosure_bot/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py
from datetime import date
from foreclosure_bot.models import Case, Parcel, Person, SheetRow


def test_case_minimal():
    c = Case(case_number="2024CP0801234", date_filed=date(2024, 5, 1))
    assert c.tax_map_number is None


def test_parcel_with_address():
    p = Parcel(
        tax_map_number="123-45-67-001",
        owner_raw="SMITH JOHN A & SMITH MARY B",
        site_street="123 MAIN ST",
        site_city="MONCKS CORNER",
        site_state="SC",
        site_zip="29461",
    )
    assert p.site_state == "SC"


def test_person_key_normalization():
    p = Person(first="John", middle="A", last="Smith", zip_code="29461")
    assert p.key() == "smith|john|a|29461"


def test_person_key_handles_missing_middle_and_zip():
    p = Person(first="JANE", middle=None, last="DOE", zip_code=None)
    assert p.key() == "doe|jane||"


def test_sheet_row_round_trip():
    r = SheetRow(
        case_number="X", date_filed=date(2024, 1, 1),
        owner_name="John Smith", street="1 St", city="C", state="SC", zip="29461",
        mobile_1="8435551111", mobile_2=None, mobile_3=None,
    )
    d = r.model_dump(mode="json")
    assert d["mobile_2"] is None
    assert d["date_filed"] == "2024-01-01"
```

- [ ] **Step 2: Run test to verify fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `models.py`**

```python
# src/foreclosure_bot/models.py
from datetime import date
from pydantic import BaseModel


class Case(BaseModel):
    case_number: str
    date_filed: date
    tax_map_number: str | None = None


class Parcel(BaseModel):
    tax_map_number: str
    owner_raw: str | None = None
    site_street: str | None = None
    site_city: str | None = None
    site_state: str | None = "SC"
    site_zip: str | None = None


class Person(BaseModel):
    first: str
    middle: str | None = None
    last: str
    zip_code: str | None = None

    def key(self) -> str:
        parts = [self.last, self.first, self.middle or "", self.zip_code or ""]
        return "|".join(p.lower().strip() for p in parts)

    def display_name(self) -> str:
        bits = [self.first, self.middle, self.last]
        return " ".join(b for b in bits if b)


class SkipTraceResult(BaseModel):
    person_key: str
    mobiles: list[str]


class SheetRow(BaseModel):
    case_number: str
    date_filed: date
    owner_name: str
    street: str
    city: str
    state: str
    zip: str
    mobile_1: str | None = None
    mobile_2: str | None = None
    mobile_3: str | None = None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_models.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/models.py tests/test_models.py
git commit -m "feat(models): pydantic domain types for case, parcel, person"
```

---

### Task 4: Dedupe schema + connection

**Files:**
- Create: `src/foreclosure_bot/dedupe.py`
- Create: `tests/test_dedupe.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create the conftest fixture**

```python
# tests/conftest.py
import pytest
from foreclosure_bot.dedupe import Store


@pytest.fixture
def store() -> Store:
    s = Store(":memory:")
    s.init_schema()
    return s
```

- [ ] **Step 2: Write the failing schema test**

```python
# tests/test_dedupe.py
def test_init_schema_creates_all_tables(store):
    rows = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [r[0] for r in rows]
    assert "cases" in names
    assert "parcels" in names
    assert "skip_traces" in names
    assert "sheet_rows" in names
    assert "errors" in names
    assert "state" in names


def test_sheet_rows_unique_constraint(store):
    store.conn.execute(
        "INSERT INTO sheet_rows(case_number, person_key) VALUES('A','p1')"
    )
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute(
            "INSERT INTO sheet_rows(case_number, person_key) VALUES('A','p1')"
        )
```

- [ ] **Step 3: Run to verify fail**

Run: `uv run pytest tests/test_dedupe.py -v`
Expected: ImportError.

- [ ] **Step 4: Implement `Store.__init__` + `init_schema`**

```python
# src/foreclosure_bot/dedupe.py
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_number     TEXT PRIMARY KEY,
    date_filed      DATE NOT NULL,
    tax_map_number  TEXT,
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

CREATE TABLE IF NOT EXISTS parcels (
    tax_map_number  TEXT PRIMARY KEY,
    owner_raw       TEXT,
    site_street     TEXT,
    site_city       TEXT,
    site_state      TEXT,
    site_zip        TEXT,
    resolved_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skip_traces (
    id              INTEGER PRIMARY KEY,
    person_key      TEXT NOT NULL UNIQUE,
    owner_name      TEXT NOT NULL,
    site_street     TEXT,
    site_city       TEXT,
    site_state      TEXT,
    site_zip        TEXT,
    mobiles_json    TEXT,
    traced_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sheet_rows (
    id              INTEGER PRIMARY KEY,
    case_number     TEXT NOT NULL,
    person_key      TEXT NOT NULL,
    written_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_number, person_key)
);

CREATE TABLE IF NOT EXISTS errors (
    id              INTEGER PRIMARY KEY,
    occurred_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stage           TEXT,
    case_number     TEXT,
    message         TEXT,
    traceback       TEXT
);

CREATE TABLE IF NOT EXISTS state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_dedupe.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/foreclosure_bot/dedupe.py tests/test_dedupe.py tests/conftest.py
git commit -m "feat(dedupe): SQLite schema with UNIQUE constraints"
```

---

### Task 5: Dedupe — case helpers

**Files:**
- Modify: `src/foreclosure_bot/dedupe.py`
- Modify: `tests/test_dedupe.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/test_dedupe.py (append)
from datetime import date
from foreclosure_bot.models import Case


def test_seen_case_numbers_returns_set(store):
    store.conn.execute(
        "INSERT INTO cases(case_number, date_filed, status) VALUES('A','2024-01-01','new')"
    )
    store.conn.execute(
        "INSERT INTO cases(case_number, date_filed, status) VALUES('B','2024-01-02','completed')"
    )
    assert store.seen_case_numbers() == {"A", "B"}


def test_upsert_case_inserts(store):
    c = Case(case_number="X", date_filed=date(2024, 5, 1), tax_map_number="123")
    store.upsert_case(c, status="new")
    row = store.conn.execute(
        "SELECT case_number, tax_map_number, status FROM cases WHERE case_number='X'"
    ).fetchone()
    assert row == ("X", "123", "new")


def test_upsert_case_updates_last_seen_only(store):
    c = Case(case_number="X", date_filed=date(2024, 5, 1), tax_map_number="123")
    store.upsert_case(c, status="new")
    store.upsert_case(c, status="ignored_on_update")  # status should not regress
    row = store.conn.execute(
        "SELECT status FROM cases WHERE case_number='X'"
    ).fetchone()
    assert row[0] == "new"  # initial status preserved


def test_set_case_status(store):
    c = Case(case_number="X", date_filed=date(2024, 5, 1))
    store.upsert_case(c, status="new")
    store.set_case_status("X", "completed")
    row = store.conn.execute("SELECT status FROM cases WHERE case_number='X'").fetchone()
    assert row[0] == "completed"


def test_load_incomplete_cases_returns_new_and_gis_done(store):
    store.conn.executemany(
        "INSERT INTO cases(case_number, date_filed, status) VALUES(?,?,?)",
        [
            ("A", "2024-01-01", "new"),
            ("B", "2024-01-02", "gis_done"),
            ("C", "2024-01-03", "completed"),
            ("D", "2024-01-04", "skipped_entity"),
            ("E", "2024-01-05", "error"),
        ],
    )
    nums = {c.case_number for c in store.load_incomplete_cases()}
    assert nums == {"A", "B", "E"}  # 'error' rows retried
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_dedupe.py -v -k "case"`
Expected: AttributeError on `seen_case_numbers`.

- [ ] **Step 3: Append helpers**

```python
# src/foreclosure_bot/dedupe.py (append)
from .models import Case


class Store:  # extend
    def seen_case_numbers(self) -> set[str]:
        rows = self.conn.execute("SELECT case_number FROM cases").fetchall()
        return {r[0] for r in rows}

    def upsert_case(self, case: Case, status: str) -> None:
        self.conn.execute(
            """INSERT INTO cases(case_number, date_filed, tax_map_number, status)
                 VALUES(?, ?, ?, ?)
               ON CONFLICT(case_number) DO UPDATE SET
                 last_seen_at = CURRENT_TIMESTAMP,
                 tax_map_number = COALESCE(cases.tax_map_number, excluded.tax_map_number)""",
            (case.case_number, case.date_filed.isoformat(), case.tax_map_number, status),
        )

    def set_case_status(self, case_number: str, status: str) -> None:
        self.conn.execute(
            "UPDATE cases SET status=?, last_seen_at=CURRENT_TIMESTAMP WHERE case_number=?",
            (status, case_number),
        )

    def load_incomplete_cases(self) -> list[Case]:
        rows = self.conn.execute(
            """SELECT case_number, date_filed, tax_map_number FROM cases
               WHERE status IN ('new','gis_done','error')"""
        ).fetchall()
        from datetime import date as _date
        return [
            Case(
                case_number=r[0],
                date_filed=_date.fromisoformat(r[1]),
                tax_map_number=r[2],
            )
            for r in rows
        ]
```

Note the `helpers` were appended to the existing `Store` class — re-open it in the same file (don't redeclare) by adding methods to the original class definition. Apply the new methods inside the existing class body in `dedupe.py`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_dedupe.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): case upsert, status transitions, incomplete-case loader"
```

---

### Task 6: Dedupe — parcel, skip-trace, sheet-row, error helpers

**Files:**
- Modify: `src/foreclosure_bot/dedupe.py`
- Modify: `tests/test_dedupe.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/test_dedupe.py (append)
import json
from foreclosure_bot.models import Parcel


def test_parcel_upsert_and_get(store):
    p = Parcel(tax_map_number="T1", owner_raw="X", site_street="1 St",
               site_city="C", site_state="SC", site_zip="29461")
    store.upsert_parcel(p)
    got = store.get_parcel("T1")
    assert got.owner_raw == "X"
    assert got.site_zip == "29461"


def test_get_parcel_missing_returns_none(store):
    assert store.get_parcel("nope") is None


def test_skip_trace_cache(store):
    store.cache_skip_trace(
        person_key="smith|john||29461",
        owner_name="John Smith",
        street="1 St", city="C", state="SC", zip_="29461",
        mobiles=["8435551111"],
    )
    cached = store.get_skip_trace("smith|john||29461")
    assert cached == ["8435551111"]
    assert store.get_skip_trace("nope") is None


def test_skip_trace_cache_idempotent(store):
    for _ in range(2):
        store.cache_skip_trace(
            person_key="k", owner_name="n", street=None, city=None,
            state=None, zip_=None, mobiles=[],
        )
    count = store.conn.execute("SELECT COUNT(*) FROM skip_traces").fetchone()[0]
    assert count == 1


def test_record_sheet_row_first_call_returns_true(store):
    assert store.record_sheet_row("CASE1", "p1") is True


def test_record_sheet_row_second_call_returns_false(store):
    store.record_sheet_row("CASE1", "p1")
    assert store.record_sheet_row("CASE1", "p1") is False


def test_log_error(store):
    store.log_error(stage="court", case_number="X", message="boom", traceback="tb")
    row = store.conn.execute(
        "SELECT stage, case_number, message FROM errors"
    ).fetchone()
    assert row == ("court", "X", "boom")


def test_state_set_and_get(store):
    store.set_state("backfill_completed_at", "2024-05-01T00:00:00Z")
    assert store.get_state("backfill_completed_at") == "2024-05-01T00:00:00Z"
    assert store.get_state("missing") is None
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_dedupe.py -v`
Expected: AttributeError on the new methods.

- [ ] **Step 3: Append helpers to `Store`**

```python
# src/foreclosure_bot/dedupe.py (extend Store)
import json
from .models import Parcel


# inside class Store:

    def upsert_parcel(self, parcel: Parcel) -> None:
        self.conn.execute(
            """INSERT INTO parcels(tax_map_number, owner_raw, site_street, site_city,
                                   site_state, site_zip)
                 VALUES(?,?,?,?,?,?)
               ON CONFLICT(tax_map_number) DO UPDATE SET
                 owner_raw=excluded.owner_raw,
                 site_street=excluded.site_street,
                 site_city=excluded.site_city,
                 site_state=excluded.site_state,
                 site_zip=excluded.site_zip,
                 resolved_at=CURRENT_TIMESTAMP""",
            (parcel.tax_map_number, parcel.owner_raw, parcel.site_street,
             parcel.site_city, parcel.site_state, parcel.site_zip),
        )

    def get_parcel(self, tax_map_number: str) -> Parcel | None:
        row = self.conn.execute(
            """SELECT tax_map_number, owner_raw, site_street, site_city, site_state, site_zip
                 FROM parcels WHERE tax_map_number=?""",
            (tax_map_number,),
        ).fetchone()
        if not row:
            return None
        return Parcel(
            tax_map_number=row[0], owner_raw=row[1], site_street=row[2],
            site_city=row[3], site_state=row[4], site_zip=row[5],
        )

    def cache_skip_trace(self, person_key: str, owner_name: str,
                         street: str | None, city: str | None,
                         state: str | None, zip_: str | None,
                         mobiles: list[str]) -> None:
        self.conn.execute(
            """INSERT INTO skip_traces(person_key, owner_name, site_street, site_city,
                                       site_state, site_zip, mobiles_json)
                 VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(person_key) DO UPDATE SET
                 mobiles_json=excluded.mobiles_json,
                 traced_at=CURRENT_TIMESTAMP""",
            (person_key, owner_name, street, city, state, zip_, json.dumps(mobiles)),
        )

    def get_skip_trace(self, person_key: str) -> list[str] | None:
        row = self.conn.execute(
            "SELECT mobiles_json FROM skip_traces WHERE person_key=?",
            (person_key,),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def record_sheet_row(self, case_number: str, person_key: str) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO sheet_rows(case_number, person_key) VALUES(?, ?)",
                (case_number, person_key),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def log_error(self, stage: str, case_number: str | None,
                  message: str, traceback: str) -> None:
        self.conn.execute(
            """INSERT INTO errors(stage, case_number, message, traceback)
                 VALUES(?,?,?,?)""",
            (stage, case_number, message, traceback),
        )

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO state(key, value) VALUES(?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (key, value),
        )

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM state WHERE key=?", (key,),
        ).fetchone()
        return row[0] if row else None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_dedupe.py -v`
Expected: all dedupe tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): parcel/skip_trace/sheet_row/error/state helpers"
```

---

### Task 7: Tracerfy client

**Files:**
- Create: `src/foreclosure_bot/tracerfy.py`
- Create: `tests/test_tracerfy.py`

> **Note for the engineer:** Tracerfy's exact endpoint path and response shape need to be confirmed against their current API docs (the user has an active key — they can hand you a sample `curl` command). The client below is structured around the most common pattern (POST JSON, return phones list with `type` field). Adjust the path/keys in `_parse_response` if the live API differs — the rest of the abstraction is unaffected.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tracerfy.py
import respx
import httpx
import pytest
from foreclosure_bot.tracerfy import TracerfyClient
from foreclosure_bot.models import Person


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_returns_mobiles_only():
    respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        return_value=httpx.Response(
            200,
            json={
                "phones": [
                    {"number": "8435551111", "type": "mobile"},
                    {"number": "8435552222", "type": "landline"},
                    {"number": "8435553333", "type": "mobile"},
                    {"number": "8435554444", "type": "voip"},
                ]
            },
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="John", last="Smith", zip_code="29461")
    mobiles = await c.skip_trace(person, street="1 St", city="C", state="SC", zip_="29461")
    assert mobiles == ["8435551111", "8435553333"]


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_truncates_to_three():
    respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        return_value=httpx.Response(
            200,
            json={"phones": [{"number": str(i)*10, "type": "mobile"} for i in range(5)]},
        )
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="J", last="D")
    mobiles = await c.skip_trace(person, street=None, city=None, state=None, zip_=None)
    assert len(mobiles) == 3


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_retries_on_5xx():
    route = respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json={"phones": []}),
        ]
    )
    c = TracerfyClient(api_key="tk")
    person = Person(first="J", last="D")
    mobiles = await c.skip_trace(person, street=None, city=None, state=None, zip_=None)
    assert mobiles == []
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_skip_trace_gives_up_after_max_retries():
    respx.post("https://api.tracerfy.com/v1/skip-trace").mock(
        return_value=httpx.Response(503)
    )
    c = TracerfyClient(api_key="tk", max_retries=2)
    person = Person(first="J", last="D")
    with pytest.raises(httpx.HTTPStatusError):
        await c.skip_trace(person, street=None, city=None, state=None, zip_=None)
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_tracerfy.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `tracerfy.py`**

```python
# src/foreclosure_bot/tracerfy.py
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_tracerfy.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/tracerfy.py tests/test_tracerfy.py
git commit -m "feat(tracerfy): async client with retries, mobile-only filter"
```

---

### Task 8: Sheet writer

**Files:**
- Create: `src/foreclosure_bot/sheet_writer.py`
- Create: `tests/test_sheet_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sheet_writer.py
from datetime import date
import respx
import httpx
import pytest
from foreclosure_bot.sheet_writer import SheetWriter
from foreclosure_bot.models import SheetRow


def make_row():
    return SheetRow(
        case_number="2024CP0801234", date_filed=date(2024, 5, 1),
        owner_name="John Smith", street="1 Main", city="C", state="SC", zip="29461",
        mobile_1="8435551111",
    )


@pytest.mark.asyncio
@respx.mock
async def test_append_posts_json_with_token():
    route = respx.post("https://script.google.com/exec").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    w = SheetWriter(url="https://script.google.com/exec", token="tok123")
    ok = await w.append(make_row())
    assert ok is True
    assert route.called
    body = route.calls.last.request.read().decode()
    assert "tok123" in body
    assert "2024CP0801234" in body


@pytest.mark.asyncio
@respx.mock
async def test_append_returns_false_on_non_200():
    respx.post("https://script.google.com/exec").mock(
        return_value=httpx.Response(500)
    )
    w = SheetWriter(url="https://script.google.com/exec", token="t")
    ok = await w.append(make_row())
    assert ok is False


@pytest.mark.asyncio
@respx.mock
async def test_append_returns_false_when_apps_script_reports_error():
    respx.post("https://script.google.com/exec").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "unauthorized"})
    )
    w = SheetWriter(url="https://script.google.com/exec", token="t")
    ok = await w.append(make_row())
    assert ok is False
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_sheet_writer.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/foreclosure_bot/sheet_writer.py
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_sheet_writer.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/sheet_writer.py tests/test_sheet_writer.py
git commit -m "feat(sheet_writer): POST SheetRow to Apps Script webhook"
```

---

### Task 9: GIS lookup — owner-string parser

**Files:**
- Create: `src/foreclosure_bot/gis_lookup.py`
- Create: `tests/test_gis_lookup.py`

- [ ] **Step 1: Write the failing parser tests**

```python
# tests/test_gis_lookup.py
from foreclosure_bot.gis_lookup import parse_owners, is_entity, OwnerName


def test_is_entity_detects_llc():
    assert is_entity("ABC PROPERTIES LLC")
    assert is_entity("Some L.L.C.")
    assert is_entity("XYZ INC")
    assert is_entity("Acme TRUST")
    assert is_entity("THE ESTATE OF Mary Jones")
    assert is_entity("Wells Fargo BANK NA")


def test_is_entity_negatives():
    assert not is_entity("SMITH JOHN A")
    assert not is_entity("DOE JANE")


def test_parse_owners_single_individual():
    out = parse_owners("SMITH JOHN A")
    assert out == [OwnerName(first="JOHN", middle="A", last="SMITH")]


def test_parse_owners_no_middle():
    out = parse_owners("DOE JANE")
    assert out == [OwnerName(first="JANE", middle=None, last="DOE")]


def test_parse_owners_couple_ampersand():
    out = parse_owners("SMITH JOHN A & SMITH MARY B")
    assert out == [
        OwnerName(first="JOHN", middle="A", last="SMITH"),
        OwnerName(first="MARY", middle="B", last="SMITH"),
    ]


def test_parse_owners_couple_and():
    out = parse_owners("SMITH JOHN AND DOE MARY")
    assert len(out) == 2
    assert out[0].last == "SMITH"
    assert out[1].last == "DOE"


def test_parse_owners_couple_semicolon():
    out = parse_owners("SMITH JOHN; DOE JANE")
    assert len(out) == 2


def test_parse_owners_drops_entities():
    out = parse_owners("ABC LLC & SMITH JOHN")
    assert out == [OwnerName(first="JOHN", middle=None, last="SMITH")]


def test_parse_owners_all_entity_returns_empty():
    out = parse_owners("ABC LLC & XYZ TRUST")
    assert out == []


def test_parse_owners_empty_string():
    assert parse_owners("") == []
    assert parse_owners(None) == []
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_gis_lookup.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement parser**

```python
# src/foreclosure_bot/gis_lookup.py
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_gis_lookup.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/gis_lookup.py tests/test_gis_lookup.py
git commit -m "feat(gis): owner-string parser + entity filter"
```

---

### Task 10: GIS lookup — ArcGIS REST query

**Files:**
- Modify: `src/foreclosure_bot/gis_lookup.py`
- Modify: `tests/test_gis_lookup.py`
- Create: `tests/fixtures/arcgis_response.json`

- [ ] **Step 1: Create the fixture**

```json
// tests/fixtures/arcgis_response.json
{
  "features": [
    {
      "attributes": {
        "PIN": "123-45-67-001",
        "OWNER": "SMITH JOHN A & SMITH MARY B",
        "SITE_ADDRESS": "123 MAIN ST",
        "SITE_CITY": "MONCKS CORNER",
        "SITE_ZIP": "29461"
      }
    }
  ]
}
```

- [ ] **Step 2: Append failing tests**

```python
# tests/test_gis_lookup.py (append)
import json
from pathlib import Path
import respx
import httpx
import pytest
from foreclosure_bot.gis_lookup import GisClient, GisFieldMap


FIXTURE = Path(__file__).parent / "fixtures" / "arcgis_response.json"


def fields():
    return GisFieldMap(pin="PIN", owner="OWNER", address="SITE_ADDRESS",
                      city="SITE_CITY", zip="SITE_ZIP")


@pytest.mark.asyncio
@respx.mock
async def test_query_returns_parcel():
    respx.get("https://gis.example.com/query").mock(
        return_value=httpx.Response(200, content=FIXTURE.read_bytes())
    )
    c = GisClient(query_url="https://gis.example.com/query", fields=fields())
    p = await c.query("123-45-67-001")
    assert p is not None
    assert p.owner_raw == "SMITH JOHN A & SMITH MARY B"
    assert p.site_street == "123 MAIN ST"
    assert p.site_city == "MONCKS CORNER"
    assert p.site_zip == "29461"
    assert p.site_state == "SC"


@pytest.mark.asyncio
@respx.mock
async def test_query_returns_none_when_no_features():
    respx.get("https://gis.example.com/query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )
    c = GisClient(query_url="https://gis.example.com/query", fields=fields())
    assert await c.query("nope") is None


@pytest.mark.asyncio
@respx.mock
async def test_query_uses_pin_field_in_where_clause():
    route = respx.get("https://gis.example.com/query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )
    c = GisClient(query_url="https://gis.example.com/query", fields=fields())
    await c.query("ABC")
    assert "PIN='ABC'" in route.calls.last.request.url.params["where"]
```

- [ ] **Step 3: Run to verify fail**

Run: `uv run pytest tests/test_gis_lookup.py -v -k "query"`
Expected: ImportError on `GisClient`.

- [ ] **Step 4: Implement**

```python
# src/foreclosure_bot/gis_lookup.py (append)
import httpx
from dataclasses import dataclass
from .models import Parcel


@dataclass(frozen=True)
class GisFieldMap:
    pin: str
    owner: str
    address: str
    city: str
    zip: str


class GisClient:
    def __init__(self, query_url: str, fields: GisFieldMap, timeout: float = 30.0):
        self.query_url = query_url
        self.fields = fields
        self.timeout = timeout

    async def query(self, tax_map_number: str) -> Parcel | None:
        # Escape single quotes in PIN to prevent broken WHERE clauses.
        safe_pin = tax_map_number.replace("'", "''")
        params = {
            "where": f"{self.fields.pin}='{safe_pin}'",
            "outFields": ",".join([
                self.fields.owner, self.fields.address,
                self.fields.city, self.fields.zip,
            ]),
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
        return Parcel(
            tax_map_number=tax_map_number,
            owner_raw=attrs.get(self.fields.owner),
            site_street=attrs.get(self.fields.address),
            site_city=attrs.get(self.fields.city),
            site_state="SC",
            site_zip=str(attrs.get(self.fields.zip) or "") or None,
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_gis_lookup.py -v`
Expected: 13 passed.

- [ ] **Step 6: Commit**

```bash
git add src/foreclosure_bot/gis_lookup.py tests/test_gis_lookup.py tests/fixtures/arcgis_response.json
git commit -m "feat(gis): ArcGIS REST query client"
```

---

### Task 11: Court scraper — fixture-based parsing

**Files:**
- Create: `src/foreclosure_bot/court_scraper.py`
- Create: `tests/test_court_scraper.py`
- Create: `tests/fixtures/court_search_results.html`
- Create: `tests/fixtures/court_case_detail.html`

> **Note for the engineer:** The Playwright driving code (form submit, click-through, pagination) cannot be unit-tested without the live site, so it's covered by an integration smoke test in Task 16. The parser logic that turns DOM into `Case` objects IS unit-testable — that's what this task does. Capture the fixtures by visiting the site once with the browser dev tools open and saving the HTML; if you don't have the live HTML yet, write the parser against the structure documented in the spec and update the fixtures during deploy verification.

- [ ] **Step 1: Create minimal fixture HTMLs**

`tests/fixtures/court_search_results.html`:
```html
<html><body>
<table id="ctl00_ctl00_MainContent_MainContent_caseSearch_GridView1">
  <tr><th>Case #</th><th>Date Filed</th></tr>
  <tr>
    <td><a href="CaseDetails.aspx?ID=2024CP0801234">2024CP0801234</a></td>
    <td>05/01/2024</td>
  </tr>
  <tr>
    <td><a href="CaseDetails.aspx?ID=2024CP0805678">2024CP0805678</a></td>
    <td>05/02/2024</td>
  </tr>
</table>
</body></html>
```

`tests/fixtures/court_case_detail.html`:
```html
<html><body>
<table>
  <tr><td>Case Number:</td><td>2024CP0801234</td></tr>
  <tr><td>Tax Map #:</td><td>123-45-67-001</td></tr>
</table>
</body></html>
```

- [ ] **Step 2: Write the failing parser tests**

```python
# tests/test_court_scraper.py
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
```

- [ ] **Step 3: Run to verify fail**

Run: `uv run pytest tests/test_court_scraper.py -v`
Expected: ImportError.

- [ ] **Step 4: Add `lxml` to dev deps**

Modify `pyproject.toml` `[project.optional-dependencies] dev = [...]` to include `"lxml>=5.2"` and `"beautifulsoup4>=4.12"`. Run `uv pip install -e ".[dev]"`.

- [ ] **Step 5: Implement parsers**

```python
# src/foreclosure_bot/court_scraper.py
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
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_court_scraper.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/foreclosure_bot/court_scraper.py tests/test_court_scraper.py tests/fixtures/court_search_results.html tests/fixtures/court_case_detail.html pyproject.toml
git commit -m "feat(court): HTML parsers for search results + case detail"
```

---

### Task 12: Court scraper — Playwright driver

**Files:**
- Modify: `src/foreclosure_bot/court_scraper.py`

> **Engineer note:** This task wires the parsers from Task 11 into a real Playwright session. There are no unit tests for this code (it touches a live site); Task 16 covers integration. Selectors below are the **expected** structure based on the SC PublicIndex pattern; verify and adjust during the deploy-time smoke test.

- [ ] **Step 1: Append the driver class**

```python
# src/foreclosure_bot/court_scraper.py (append)
import asyncio
import random
from datetime import date
from collections.abc import AsyncIterator
from playwright.async_api import async_playwright, Page


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
```

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "from foreclosure_bot.court_scraper import CourtScraper; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Verify existing tests still pass**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/foreclosure_bot/court_scraper.py
git commit -m "feat(court): Playwright driver — disclaimer, search, pagination"
```

---

### Task 13: Email alerts with throttle

**Files:**
- Create: `src/foreclosure_bot/alerts.py`
- Create: `tests/test_alerts.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_alerts.py
from unittest.mock import MagicMock, patch
from foreclosure_bot.alerts import AlertSender


def test_send_calls_smtp(store):
    sender = AlertSender(
        store=store, host="h", port=587, user="u", password="p",
        to="t@x.com",
    )
    with patch("foreclosure_bot.alerts.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        sender.notify(stage="court", message="boom", traceback="tb")
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("u", "p")
        smtp.sendmail.assert_called_once()


def test_throttle_blocks_second_within_hour(store):
    sender = AlertSender(
        store=store, host="h", port=587, user="u", password="p",
        to="t@x.com",
    )
    with patch("foreclosure_bot.alerts.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        sender.notify(stage="court", message="m", traceback="t")
        sender.notify(stage="court", message="m", traceback="t")
        assert smtp.sendmail.call_count == 1


def test_throttle_independent_per_stage(store):
    sender = AlertSender(
        store=store, host="h", port=587, user="u", password="p",
        to="t@x.com",
    )
    with patch("foreclosure_bot.alerts.smtplib.SMTP") as smtp_cls:
        smtp = MagicMock()
        smtp_cls.return_value.__enter__.return_value = smtp
        sender.notify(stage="court", message="m", traceback="t")
        sender.notify(stage="gis", message="m", traceback="t")
        assert smtp.sendmail.call_count == 2
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/foreclosure_bot/alerts.py
import smtplib
import time
from email.message import EmailMessage
from .dedupe import Store


class AlertSender:
    THROTTLE_SECS = 3600

    def __init__(self, *, store: Store, host: str, port: int,
                 user: str, password: str, to: str):
        self.store = store
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.to = to

    def notify(self, *, stage: str, message: str, traceback: str) -> None:
        if self._throttled(stage):
            return
        msg = EmailMessage()
        msg["Subject"] = f"[foreclosure-bot] error in {stage}"
        msg["From"] = self.user
        msg["To"] = self.to
        msg.set_content(f"Stage: {stage}\n\n{message}\n\n{traceback}")
        with smtplib.SMTP(self.host, self.port) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.sendmail(self.user, [self.to], msg.as_string())
        self.store.set_state(self._key(stage), str(int(time.time())))

    def _throttled(self, stage: str) -> bool:
        last = self.store.get_state(self._key(stage))
        if last is None:
            return False
        return (time.time() - int(last)) < self.THROTTLE_SECS

    @staticmethod
    def _key(stage: str) -> str:
        return f"alert_last_sent::{stage}"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_alerts.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/foreclosure_bot/alerts.py tests/test_alerts.py
git commit -m "feat(alerts): SMTP sender with per-stage hourly throttle"
```

---

### Task 14: Pipeline orchestrator

**Files:**
- Create: `src/foreclosure_bot/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing end-to-end test**

```python
# tests/test_pipeline.py
from datetime import date
from unittest.mock import AsyncMock, MagicMock
import pytest
from foreclosure_bot.pipeline import Pipeline
from foreclosure_bot.models import Case, Parcel, SheetRow


@pytest.mark.asyncio
async def test_pipeline_writes_one_row_per_individual(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1),
                   tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="SMITH JOHN A & SMITH MARY B",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(side_effect=[
        ["8435551111"],
        ["8435552222", "8435553333"],
    ])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()

    assert tracerfy.skip_trace.await_count == 2
    assert sheets.append.await_count == 2
    rows = store.conn.execute("SELECT case_number, person_key FROM sheet_rows").fetchall()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_pipeline_dedupe_prevents_second_write(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1), tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="SMITH JOHN A",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(return_value=["8435551111"])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()
    await p.run()  # second run — should write nothing new

    assert sheets.append.await_count == 1


@pytest.mark.asyncio
async def test_pipeline_skips_entity_owner(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1), tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="ABC PROPERTIES LLC",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    sheets = MagicMock()

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()

    tracerfy.skip_trace.assert_not_called()
    status = store.conn.execute("SELECT status FROM cases WHERE case_number='C1'").fetchone()[0]
    assert status == "skipped_entity"


@pytest.mark.asyncio
async def test_pipeline_writes_row_with_no_mobiles(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        yield Case(case_number="C1", date_filed=date(2024, 5, 1), tax_map_number="T1")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(return_value=Parcel(
        tax_map_number="T1", owner_raw="SMITH JOHN",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(return_value=[])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=200,
    )
    await p.run()

    sheets.append.assert_awaited_once()
    posted: SheetRow = sheets.append.await_args.args[0]
    assert posted.mobile_1 is None


@pytest.mark.asyncio
async def test_pipeline_backfill_cap_stops_skip_trace(store):
    scraper = MagicMock()
    async def fake_iter(start, end, seen):
        for i in range(5):
            yield Case(case_number=f"C{i}", date_filed=date(2024, 5, 1),
                       tax_map_number=f"T{i}")
    scraper.discover_cases = fake_iter

    gis = MagicMock()
    gis.query = AsyncMock(side_effect=lambda tm: Parcel(
        tax_map_number=tm, owner_raw=f"SMITH PERSON{tm}",
        site_street="1 Main", site_city="C", site_state="SC", site_zip="29461",
    ))

    tracerfy = MagicMock()
    tracerfy.skip_trace = AsyncMock(return_value=[])

    sheets = MagicMock()
    sheets.append = AsyncMock(return_value=True)

    p = Pipeline(
        store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
        sheets=sheets, lookback_days=7, backfill_days=30,
        backfill_max_lookups=2,  # CAP
    )
    await p.run()

    assert tracerfy.skip_trace.await_count == 2
    incomplete = store.conn.execute(
        "SELECT COUNT(*) FROM cases WHERE status='gis_done'"
    ).fetchone()[0]
    assert incomplete == 3
```

- [ ] **Step 2: Run to verify fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/foreclosure_bot/pipeline.py
from datetime import date, datetime, timedelta, timezone
from .dedupe import Store
from .gis_lookup import GisClient, parse_owners
from .models import Case, Person, SheetRow
from .sheet_writer import SheetWriter
from .tracerfy import TracerfyClient


class Pipeline:
    def __init__(
        self,
        *,
        store: Store,
        scraper,
        gis: GisClient,
        tracerfy: TracerfyClient,
        sheets: SheetWriter,
        lookback_days: int,
        backfill_days: int,
        backfill_max_lookups: int,
    ):
        self.store = store
        self.scraper = scraper
        self.gis = gis
        self.tracerfy = tracerfy
        self.sheets = sheets
        self.lookback_days = lookback_days
        self.backfill_days = backfill_days
        self.backfill_max_lookups = backfill_max_lookups
        self._tracerfy_calls_this_run = 0

    async def run(self) -> None:
        # 1. Resume incomplete cases
        working: dict[str, Case] = {
            c.case_number: c for c in self.store.load_incomplete_cases()
        }

        # 2. Discover new cases
        is_backfill = self.store.get_state("backfill_completed_at") is None
        days = self.backfill_days if is_backfill else self.lookback_days
        end = date.today()
        start = end - timedelta(days=days)
        already_seen = self.store.seen_case_numbers()

        async for case in self.scraper.discover_cases(start, end, already_seen):
            status = "skipped_no_taxmap" if case.tax_map_number is None else "new"
            self.store.upsert_case(case, status=status)
            if case.tax_map_number:
                working[case.case_number] = case

        # 3-6. Process working set
        for case in list(working.values()):
            try:
                await self._process_case(case, is_backfill)
            except Exception as exc:  # noqa: BLE001 — caught & logged at boundary
                import traceback
                self.store.log_error(
                    stage="pipeline", case_number=case.case_number,
                    message=str(exc), traceback=traceback.format_exc(),
                )
                self.store.set_case_status(case.case_number, "error")

        # Set backfill complete when no incomplete cases remain
        if is_backfill:
            remaining = self.store.conn.execute(
                "SELECT COUNT(*) FROM cases WHERE status IN ('new','gis_done','error')"
            ).fetchone()[0]
            if remaining == 0:
                self.store.set_state(
                    "backfill_completed_at",
                    datetime.now(timezone.utc).isoformat(),
                )

    async def _process_case(self, case: Case, is_backfill: bool) -> None:
        if case.tax_map_number is None:
            self.store.set_case_status(case.case_number, "skipped_no_taxmap")
            return

        # 3. GIS resolve
        parcel = self.store.get_parcel(case.tax_map_number)
        if parcel is None:
            parcel = await self.gis.query(case.tax_map_number)
            if parcel is None:
                self.store.set_case_status(case.case_number, "error")
                self.store.log_error(
                    stage="gis", case_number=case.case_number,
                    message="parcel not found", traceback="",
                )
                return
            self.store.upsert_parcel(parcel)
        self.store.set_case_status(case.case_number, "gis_done")

        # 4. Parse owners, drop entities
        owners = parse_owners(parcel.owner_raw)
        if not owners:
            self.store.set_case_status(case.case_number, "skipped_entity")
            return

        # 5-6. Skip trace + write
        all_written = True
        for owner in owners:
            person = Person(
                first=owner.first, middle=owner.middle, last=owner.last,
                zip_code=parcel.site_zip,
            )
            person_key = person.key()

            mobiles = self.store.get_skip_trace(person_key)
            if mobiles is None:
                if is_backfill and self._tracerfy_calls_this_run >= self.backfill_max_lookups:
                    all_written = False
                    continue
                mobiles = await self.tracerfy.skip_trace(
                    person,
                    street=parcel.site_street, city=parcel.site_city,
                    state=parcel.site_state, zip_=parcel.site_zip,
                )
                self._tracerfy_calls_this_run += 1
                self.store.cache_skip_trace(
                    person_key=person_key, owner_name=person.display_name(),
                    street=parcel.site_street, city=parcel.site_city,
                    state=parcel.site_state, zip_=parcel.site_zip,
                    mobiles=mobiles,
                )

            if not self.store.record_sheet_row(case.case_number, person_key):
                continue  # already written previously

            row = SheetRow(
                case_number=case.case_number, date_filed=case.date_filed,
                owner_name=person.display_name(),
                street=parcel.site_street or "", city=parcel.site_city or "",
                state=parcel.site_state or "SC", zip=parcel.site_zip or "",
                mobile_1=mobiles[0] if len(mobiles) > 0 else None,
                mobile_2=mobiles[1] if len(mobiles) > 1 else None,
                mobile_3=mobiles[2] if len(mobiles) > 2 else None,
            )
            ok = await self.sheets.append(row)
            if not ok:
                all_written = False
                self.store.log_error(
                    stage="sheet", case_number=case.case_number,
                    message="webhook returned non-ok", traceback="",
                )

        if all_written:
            self.store.set_case_status(case.case_number, "completed")
```

- [ ] **Step 4: Run pipeline tests**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: 5 passed.

- [ ] **Step 5: Run full suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/foreclosure_bot/pipeline.py tests/test_pipeline.py
git commit -m "feat(pipeline): orchestrator with dedupe, backfill cap, error handling"
```

---

### Task 15: Entrypoint

**Files:**
- Create: `src/foreclosure_bot/__main__.py`

- [ ] **Step 1: Implement**

```python
# src/foreclosure_bot/__main__.py
import asyncio
import sys
import traceback
from .alerts import AlertSender
from .config import Settings
from .court_scraper import CourtScraper
from .dedupe import Store
from .gis_lookup import GisClient, GisFieldMap
from .pipeline import Pipeline
from .sheet_writer import SheetWriter
from .tracerfy import TracerfyClient


async def _run() -> int:
    settings = Settings()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(settings.sqlite_path)
    store.init_schema()
    alerts = AlertSender(
        store=store, host=settings.smtp_host, port=settings.smtp_port,
        user=settings.smtp_user, password=settings.smtp_pass,
        to=settings.alert_email_to,
    )
    try:
        scraper = CourtScraper(user_agent=settings.court_user_agent)
        gis = GisClient(
            query_url=settings.arcgis_parcel_query_url,
            fields=GisFieldMap(
                pin=settings.arcgis_parcel_pin_field,
                owner=settings.arcgis_parcel_owner_field,
                address=settings.arcgis_parcel_address_field,
                city=settings.arcgis_parcel_city_field,
                zip=settings.arcgis_parcel_zip_field,
            ),
        )
        tracerfy = TracerfyClient(api_key=settings.tracerfy_api_key)
        sheets = SheetWriter(
            url=settings.sheets_webhook_url, token=settings.sheets_webhook_token,
        )
        pipeline = Pipeline(
            store=store, scraper=scraper, gis=gis, tracerfy=tracerfy,
            sheets=sheets,
            lookback_days=settings.scrape_lookback_days,
            backfill_days=settings.backfill_days,
            backfill_max_lookups=settings.backfill_max_lookups,
        )
        await pipeline.run()
        return 0
    except Exception as exc:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        try:
            alerts.notify(stage="run", message=str(exc), traceback=tb)
        except Exception:
            pass
        return 1
    finally:
        store.close()


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-check the import graph**

Run: `uv run python -c "import foreclosure_bot.__main__; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Verify full suite still green**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/foreclosure_bot/__main__.py
git commit -m "feat(entrypoint): wire pipeline + top-level error → email alert"
```

---

### Task 16: Live smoke test (manual + automated)

**Files:**
- Create: `scripts/smoke_court.py`
- Create: `scripts/smoke_gis.py`
- Create: `scripts/discover_arcgis_fields.py`

> **Engineer note:** These are manual scripts you run once during deployment to confirm assumptions about live sites. They are NOT part of the test suite.

- [ ] **Step 1: Create the ArcGIS discovery script**

```python
# scripts/discover_arcgis_fields.py
"""Hit the ArcGIS rest directory and print parcel-layer URLs + field names."""
import sys
import httpx

ROOT = "https://gis.berkeleycountysc.gov/arcgis/rest/services?f=json"


def main():
    services = httpx.get(ROOT).json().get("services", [])
    for svc in services:
        name = svc["name"]
        if "parcel" in name.lower() or "tax" in name.lower():
            url = f"https://gis.berkeleycountysc.gov/arcgis/rest/services/{name}/MapServer?f=json"
            meta = httpx.get(url).json()
            for layer in meta.get("layers", []):
                lid = layer["id"]
                lname = layer["name"]
                furl = f"https://gis.berkeleycountysc.gov/arcgis/rest/services/{name}/MapServer/{lid}?f=json"
                fmeta = httpx.get(furl).json()
                fields = [f["name"] for f in fmeta.get("fields", [])]
                print(f"\nLayer: {lname}\nQuery URL: {furl[:-7]}/query")
                print(f"Fields: {fields}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Create court smoke test**

```python
# scripts/smoke_court.py
"""Run the court scraper against the live site for the last 7 days."""
import asyncio
from datetime import date, timedelta
from foreclosure_bot.court_scraper import CourtScraper
from foreclosure_bot.config import Settings


async def main():
    s = Settings()
    scraper = CourtScraper(user_agent=s.court_user_agent)
    end = date.today()
    start = end - timedelta(days=7)
    n = 0
    async for case in scraper.discover_cases(start, end, set()):
        print(case)
        n += 1
        if n >= 3:
            break
    print(f"discovered {n} cases")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Create GIS smoke test**

```python
# scripts/smoke_gis.py
"""Look up a parcel by tax map number against the live ArcGIS service."""
import asyncio
import sys
from foreclosure_bot.config import Settings
from foreclosure_bot.gis_lookup import GisClient, GisFieldMap


async def main(pin: str):
    s = Settings()
    c = GisClient(
        query_url=s.arcgis_parcel_query_url,
        fields=GisFieldMap(
            pin=s.arcgis_parcel_pin_field, owner=s.arcgis_parcel_owner_field,
            address=s.arcgis_parcel_address_field, city=s.arcgis_parcel_city_field,
            zip=s.arcgis_parcel_zip_field,
        ),
    )
    parcel = await c.query(pin)
    print(parcel)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
```

- [ ] **Step 4: Document in README**

Append to `README.md`:

```markdown
## First-time deploy verification

1. `uv run python scripts/discover_arcgis_fields.py` — copy the query URL + field names into `.env`.
2. `uv run python scripts/smoke_gis.py 123-45-67-001` (use any known Berkeley TMS) — confirm a parcel comes back with owner + address.
3. `uv run python scripts/smoke_court.py` — confirm the scraper returns at least one case from the last 7 days. If selectors are wrong, edit `court_scraper.py` and re-run.
4. After all three pass, `systemctl enable --now foreclosure-bot.timer`.
```

- [ ] **Step 5: Commit**

```bash
git add scripts/ README.md
git commit -m "chore: live smoke-test scripts + deploy verification doc"
```

---

### Task 17: systemd units

**Files:**
- Create: `deploy/foreclosure-bot.service`
- Create: `deploy/foreclosure-bot.timer`

- [ ] **Step 1: Create the service unit**

```ini
# deploy/foreclosure-bot.service
[Unit]
Description=Berkeley County foreclosure scraper
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=botuser
WorkingDirectory=/home/botuser/foreclosure-bot
EnvironmentFile=/home/botuser/foreclosure-bot/.env
ExecStart=/home/botuser/foreclosure-bot/.venv/bin/python -m foreclosure_bot
RuntimeMaxSec=50m
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/botuser/foreclosure-bot/data /var/backups/foreclosure-bot
PrivateTmp=true
```

- [ ] **Step 2: Create the timer unit**

```ini
# deploy/foreclosure-bot.timer
[Unit]
Description=Run foreclosure-bot hourly
Requires=foreclosure-bot.service

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Commit**

```bash
git add deploy/foreclosure-bot.service deploy/foreclosure-bot.timer
git commit -m "deploy: systemd service + hourly timer"
```

---

### Task 18: Setup script + backup

**Files:**
- Create: `deploy/setup.sh`
- Create: `deploy/backup.sh`

- [ ] **Step 1: Create `setup.sh`**

```bash
#!/usr/bin/env bash
# deploy/setup.sh — one-shot provisioning for a fresh Ubuntu 24.04 VPS.
# Run as root. Assumes /home/botuser/foreclosure-bot already cloned.
set -euo pipefail

apt-get update
apt-get install -y python3.12 python3.12-venv git curl ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    sqlite3

id -u botuser >/dev/null 2>&1 || useradd -m -s /bin/bash botuser

BOT_DIR=/home/botuser/foreclosure-bot
sudo -u botuser bash <<EOF
cd "$BOT_DIR"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="\$HOME/.cargo/bin:\$HOME/.local/bin:\$PATH"
uv venv
uv pip install -e ".[dev]"
uv run playwright install chromium
EOF

mkdir -p /var/backups/foreclosure-bot
chown botuser:botuser /var/backups/foreclosure-bot
chmod 750 /var/backups/foreclosure-bot

cp "$BOT_DIR/deploy/foreclosure-bot.service" /etc/systemd/system/
cp "$BOT_DIR/deploy/foreclosure-bot.timer" /etc/systemd/system/
systemctl daemon-reload

# Nightly backup at 03:17
cat >/etc/cron.d/foreclosure-bot-backup <<EOF
17 3 * * * botuser $BOT_DIR/deploy/backup.sh
EOF

echo "Setup complete. Next steps:"
echo "  1. Edit /home/botuser/foreclosure-bot/.env (chmod 600)"
echo "  2. Run smoke tests (see README)"
echo "  3. systemctl enable --now foreclosure-bot.timer"
```

- [ ] **Step 2: Create `backup.sh`**

```bash
#!/usr/bin/env bash
# deploy/backup.sh — nightly SQLite backup, keep 7 dailies.
set -euo pipefail
BOT_DIR=/home/botuser/foreclosure-bot
BACKUP_DIR=/var/backups/foreclosure-bot
DATE=$(date +%Y-%m-%d)
sqlite3 "$BOT_DIR/data/bot.sqlite" ".backup '$BACKUP_DIR/bot-$DATE.sqlite'"
ls -1t "$BACKUP_DIR"/bot-*.sqlite | tail -n +8 | xargs -r rm
```

- [ ] **Step 3: Make executable**

```bash
chmod +x deploy/setup.sh deploy/backup.sh
```

- [ ] **Step 4: Commit**

```bash
git add deploy/setup.sh deploy/backup.sh
git commit -m "deploy: provisioning script + nightly SQLite backup"
```

---

### Task 19: Apps Script template

**Files:**
- Create: `deploy/apps_script.gs`

- [ ] **Step 1: Create the script**

```javascript
// deploy/apps_script.gs
// PASTE THIS into a new Apps Script attached to your Google Sheet.
// 1. Replace SHARED_TOKEN with the same value you set for SHEETS_WEBHOOK_TOKEN in .env.
// 2. Add a tab named "Leads" with headers in row 1:
//    Written At | Case # | Date Filed | Owner Name | Street | City | State | Zip | Mobile 1 | Mobile 2 | Mobile 3
// 3. Deploy → New deployment → Type: Web app → Execute as: Me, Access: Anyone with the link.
// 4. Copy the Web App URL into SHEETS_WEBHOOK_URL in .env.

const SHARED_TOKEN = 'replace-me-with-SHEETS_WEBHOOK_TOKEN';

function doPost(e) {
  let body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) {
    return _resp({ ok: false, error: 'bad_json' });
  }
  if (body.token !== SHARED_TOKEN) {
    return _resp({ ok: false, error: 'unauthorized' });
  }
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Leads');
  if (!sheet) return _resp({ ok: false, error: 'no_leads_tab' });
  sheet.appendRow([
    new Date(),
    body.case_number, body.date_filed,
    body.owner_name,
    body.street, body.city, body.state, body.zip,
    body.mobile_1 || '', body.mobile_2 || '', body.mobile_3 || ''
  ]);
  return _resp({ ok: true });
}

function _resp(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
```

- [ ] **Step 2: Commit**

```bash
git add deploy/apps_script.gs
git commit -m "deploy: Apps Script webhook template for Sheet writes"
```

---

### Task 20: Final integration check

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Lint**

Run: `uv run ruff check .`
Expected: no errors.

- [ ] **Step 3: Type check (best-effort)**

Run: `uv run mypy src/foreclosure_bot --ignore-missing-imports`
Expected: no errors. (Acceptable to silence individual lines with `# type: ignore[code]` if needed.)

- [ ] **Step 4: Verify the entrypoint dry-runs against an empty in-memory pipeline**

Add `tests/test_entrypoint.py`:

```python
import os
import asyncio
from unittest.mock import patch, AsyncMock
from foreclosure_bot.__main__ import _run


def test_main_runs_without_unhandled_exception(monkeypatch, tmp_path):
    monkeypatch.setenv("TRACERFY_API_KEY", "tk")
    monkeypatch.setenv("SHEETS_WEBHOOK_URL", "https://example.com/exec")
    monkeypatch.setenv("SHEETS_WEBHOOK_TOKEN", "tok")
    monkeypatch.setenv("ALERT_EMAIL_TO", "t@x.com")
    monkeypatch.setenv("SMTP_USER", "u@x.com")
    monkeypatch.setenv("SMTP_PASS", "p")
    monkeypatch.setenv("ARCGIS_PARCEL_QUERY_URL", "https://gis.example.com/query")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "bot.sqlite"))

    async def empty_iter(start, end, seen):
        if False:
            yield
    with patch("foreclosure_bot.__main__.CourtScraper") as scraper_cls:
        scraper = scraper_cls.return_value
        scraper.discover_cases = empty_iter
        rc = asyncio.run(_run())
    assert rc == 0
```

Run: `uv run pytest tests/test_entrypoint.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_entrypoint.py
git commit -m "test: end-to-end entrypoint smoke with mocked court scraper"
```

---

## Done

The bot is now ready to deploy. The deploy procedure (per `README.md`):

1. Provision a Hetzner CX22 / DigitalOcean droplet (Ubuntu 24.04).
2. Clone the repo to `/home/botuser/foreclosure-bot`.
3. Run `sudo deploy/setup.sh`.
4. Run `scripts/discover_arcgis_fields.py` to fill in the ArcGIS env vars.
5. Drop a populated `.env` (chmod 600).
6. Run the three smoke scripts.
7. `systemctl enable --now foreclosure-bot.timer`.

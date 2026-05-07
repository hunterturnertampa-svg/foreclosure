# Berkeley County SC Foreclosure Lead Bot — Design

**Date:** 2026-05-07
**Status:** Approved (pending written-spec review)
**Owner:** hunterturnertampa@gmail.com

## 1. Goal

Continuously discover newly filed Berkeley County, SC foreclosure cases, look up the recorded property owner via the county GIS, skip-trace each individual owner via the Tracerfy API for mobile phone numbers, and append every result as a row to a Google Sheet. Run unattended on an hourly schedule, 24/7, with zero duplicate rows.

## 2. Inputs and outputs

**Sources:**
- `https://publicindex.sccourts.org/Berkeley/PublicIndex/PISearch.aspx` — case discovery (Case Type = Common Pleas, Case Sub Type = Foreclosure 420, Date Type = Case Filed)
- `https://gis.berkeleycountysc.gov/arcgis/rest/services/...` — ArcGIS REST query by tax map number for owner + site address (with the public map app at `gis.berkeleycountysc.gov/maps/advanced_map/desktop.html` as the human-facing fallback)
- Tracerfy API — skip trace by name + address

**Sink:**
- A user-owned Google Sheet, written via a Google Apps Script web-app webhook the user deploys.

**Sheet schema (`Leads` tab):**

| Written At | Case # | Date Filed | Owner Name | Street | City | State | Zip | Mobile 1 | Mobile 2 | Mobile 3 |

## 3. Non-goals

- Web dashboard or UI for browsing leads (the Sheet is the UI)
- Multi-county support (Berkeley only)
- Re-processing cases on status change (only new filings are captured)
- Enrichment beyond Tracerfy (no probate, divorce, MLS, etc.)
- Landline or VoIP capture — mobiles only

## 4. Architecture

```
VPS (Hetzner CX22, Ubuntu 24.04, ~$5/mo)
  └─ systemd timer (hourly) ─► foreclosure-bot.service
        └─ pipeline orchestrator
              ├─ court_scraper   (Playwright → publicindex.sccourts.org)
              ├─ gis_lookup      (httpx → ArcGIS REST; Playwright fallback)
              ├─ tracerfy        (httpx → Tracerfy API)
              ├─ dedupe          (SQLite)
              ├─ sheet_writer    (HTTPS POST → Apps Script web app)
              └─ alerts          (SMTP, on unhandled exception)
```

### Per-run pipeline

1. **Resume incomplete cases.** Load every case from `cases` whose `status` is in (`new`, `gis_done`) — these are leftovers from prior runs (e.g. backfill-cap hits, transient GIS failures). They will be re-driven through steps 3–6.
2. **Discover new cases.** Scrape court site for cases filed in the last `SCRAPE_LOOKBACK_DAYS` days (default 7). For every case number not already in `cases`, open its detail page and extract the tax map number, then `INSERT` into `cases` with `status='new'` (or `skipped_no_taxmap` if no tax map). Add to the working set from step 1.
3. For every case in the working set with a tax map # whose tax map is not in `parcels`, query ArcGIS REST for owner string + site address and cache. Update case `status` to `gis_done`.
4. Filter LLC/INC/TRUST/CORP/LTD entities out of the owner string. Split remaining individuals on `&`, `AND`, `;`. If zero individuals remain, mark case `skipped_entity`.
5. For each individual not yet in `skip_traces`, call Tracerfy. Keep only mobile numbers (up to 3). Cache the result.
6. For each `(case_number, person_key)` not already in `sheet_rows`, POST one row to the Apps Script webhook and insert into `sheet_rows` on success. When all individuals from a case have been written, set case `status='completed'`.
7. On any unhandled exception, email an alert (rate-limited to one per stage per hour) and set the affected case's `status='error'` (it will be retried via step 1 next run).

### First run only

- `BACKFILL_DAYS=30` (overrides the lookback window in step 2 of the pipeline for the first run only).
- `BACKFILL_MAX_LOOKUPS=200` cap on Tracerfy calls during the backfill. Once the cap is hit, step 5 stops for the rest of the run; affected cases stay at `status='gis_done'` and are picked up by step 1 of the next hourly run, which has no cap.
- A `state` row in SQLite records `backfill_completed_at`. While unset, the lookback window is `BACKFILL_DAYS`; once set, the lookback drops to `SCRAPE_LOOKBACK_DAYS`. The `state` cursor is set when a run completes with no remaining `new`/`gis_done` cases older than `SCRAPE_LOOKBACK_DAYS`.

## 5. Dedupe (the core correctness requirement)

Dedupe is enforced at four levels, each by a `UNIQUE` SQLite constraint. The fourth level (`sheet_rows`) is the hard guarantee that no row is ever written to the Sheet twice, even if every cache above it is wiped.

```sql
CREATE TABLE cases (
    case_number     TEXT PRIMARY KEY,
    date_filed      DATE NOT NULL,
    tax_map_number  TEXT,
    first_seen_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status          TEXT NOT NULL  -- new | gis_done | skipped_no_taxmap | skipped_entity | completed | error
);

CREATE TABLE parcels (
    tax_map_number  TEXT PRIMARY KEY,
    owner_raw       TEXT,
    site_street     TEXT,
    site_city       TEXT,
    site_state      TEXT,
    site_zip        TEXT,
    resolved_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skip_traces (
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

CREATE TABLE sheet_rows (
    id              INTEGER PRIMARY KEY,
    case_number     TEXT NOT NULL,
    person_key      TEXT NOT NULL,
    written_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_number, person_key)
);

CREATE TABLE errors (
    id              INTEGER PRIMARY KEY,
    occurred_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stage           TEXT,
    case_number     TEXT,
    message         TEXT,
    traceback       TEXT
);

CREATE TABLE state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

### Person-key normalization

```python
def person_key(first: str, middle: str | None, last: str, zip_code: str | None) -> str:
    return "|".join(s.lower().strip() for s in (last, first, middle or "", zip_code or ""))
```

ZIP is included so two distinct "John Smith"s in different ZIPs are not collapsed, while the same John Smith on multiple foreclosures is skip-traced once and reused.

### Owner-string handling

- Entity tokens that cause a parcel to be marked `skipped_entity` (no skip trace, no row written): `LLC`, `L.L.C.`, `INC`, `INC.`, `INCORPORATED`, `CORP`, `CORPORATION`, `LTD`, `LIMITED`, `TRUST`, `TRUSTEE`, `ESTATE OF`, `BANK`, `LP`, `LLP`.
- Individual splitting: split the owner string on ` & `, ` AND `, `;`. Each fragment is parsed into `last, first middle` (Berkeley GIS uses `LASTNAME FIRSTNAME [MIDDLE]` format).
- If a parcel produces zero individuals after entity filtering, it is marked `skipped_entity` and no Tracerfy call is made.

### Empty-result rule

Per requirements, a row IS written to the sheet even when Tracerfy returns zero mobile numbers. `Mobile 1/2/3` columns are blank in that case.

## 6. Component contracts

### `court_scraper.discover_cases(start_date, end_date, already_seen: set[str]) -> Iterator[Case]`

- Accepts disclaimer page automatically.
- Submits search form (Common Pleas / Foreclosure 420 / Case Filed).
- Iterates result pages. For each case row, if its case number is in `already_seen`, skip the detail click entirely (saves time and politeness budget). Otherwise opens the detail page and yields a `Case(case_number, date_filed, tax_map_number)` (tax_map may be `None`).
- Politeness: 2–4s random delay between detail clicks, single concurrent browser context, real Chrome User-Agent.
- On CAPTCHA, 403, or repeated 5xx: stops the run, raises, exits non-zero — does not hammer.

### `gis_lookup.resolve(tax_map_number) -> Parcel | None`

- Primary: ArcGIS REST `query` endpoint with `where=PIN='<tax_map>'` (exact field name confirmed against the layer's `?f=json` metadata at deploy time).
- Returns parsed `(owner_raw, site_street, site_city, site_state, site_zip)`.
- Fallback: Playwright on the public property card page if REST returns 403 or empty.
- Returns `None` if neither path resolves the parcel.

### `tracerfy.skip_trace(person, address) -> list[str]`

- One POST per individual.
- Returns mobile-only numbers (filters out `landline`, `voip`).
- Truncates to first 3 mobiles.
- Retries 3× with exponential backoff on 5xx / network errors.
- Cached forever in `skip_traces` keyed by `person_key`.

### `sheet_writer.append(row: SheetRow) -> bool`

- Verifies `(case_number, person_key)` is not in `sheet_rows`.
- POSTs JSON to `SHEETS_WEBHOOK_URL` with header `X-Webhook-Token: $SHEETS_WEBHOOK_TOKEN`.
- On HTTP 200, inserts into `sheet_rows`.
- Returns `True` on success.

### `alerts.notify(stage, exc) -> None`

- SMTP email to `ALERT_EMAIL_TO`.
- Subject: `[foreclosure-bot] error in <stage>`.
- Body: traceback + run timestamp.
- Throttle: skips if an alert for the same stage was sent in the last hour (`state` table cursor).

## 7. Operations

### Scheduling

systemd timer (`OnCalendar=hourly`, `Persistent=true`) firing a oneshot service with `RuntimeMaxSec=50m`. Logs go to `journalctl`.

### Configuration (`.env`, mode 0600, root-only)

```
TRACERFY_API_KEY=
SHEETS_WEBHOOK_URL=
SHEETS_WEBHOOK_TOKEN=
ALERT_EMAIL_TO=hunterturnertampa@gmail.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SCRAPE_LOOKBACK_DAYS=7
BACKFILL_DAYS=30
BACKFILL_MAX_LOOKUPS=200
COURT_USER_AGENT=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
```

### Backups

`sqlite3 .backup` runs nightly via cron, keeps last 7 daily backups in `/var/backups/foreclosure-bot/`.

### Project layout

```
foreclosure-bot/
├── pyproject.toml          # uv-managed, Python 3.12
├── .env                    # secrets (chmod 600, gitignored)
├── .gitignore
├── README.md
├── src/foreclosure_bot/
│   ├── __main__.py         # entrypoint
│   ├── config.py           # env loading + validation
│   ├── pipeline.py         # orchestrator
│   ├── court_scraper.py    # Playwright
│   ├── gis_lookup.py       # ArcGIS REST + Playwright fallback
│   ├── tracerfy.py         # API client
│   ├── sheet_writer.py     # webhook POST
│   ├── dedupe.py           # SQLite + person_key
│   └── alerts.py           # SMTP
├── tests/                  # pytest, mocked HTTP per component
├── data/
│   └── bot.sqlite          # state
├── deploy/
│   ├── foreclosure-bot.service
│   ├── foreclosure-bot.timer
│   ├── backup.sh
│   └── setup.sh            # one-shot VPS provisioning
└── docs/superpowers/specs/
    └── 2026-05-07-berkeley-foreclosure-bot-design.md   # this file
```

### Apps Script (user-deployed)

```javascript
const TOKEN = 'paste-the-same-SHEETS_WEBHOOK_TOKEN-here';

function doPost(e) {
  if (e.parameter.token !== TOKEN && (e.postData && JSON.parse(e.postData.contents).token) !== TOKEN) {
    return ContentService.createTextOutput(JSON.stringify({ok: false, error: 'unauthorized'}))
      .setMimeType(ContentService.MimeType.JSON);
  }
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Leads');
  const row = JSON.parse(e.postData.contents);
  sheet.appendRow([
    new Date(),
    row.case_number, row.date_filed,
    row.owner_name,
    row.street, row.city, row.state, row.zip,
    row.mobile_1 || '', row.mobile_2 || '', row.mobile_3 || ''
  ]);
  return ContentService.createTextOutput(JSON.stringify({ok: true}))
    .setMimeType(ContentService.MimeType.JSON);
}
```

Deployed as a web app with execution access set to "Anyone with the link". The shared `WEBHOOK_TOKEN` is the actual access control.

## 8. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Court site adds CAPTCHA | Medium | Bot stops + emails on 403/CAPTCHA detection; manual re-tooling required. No silent failures. |
| ArcGIS field names differ from assumed `PIN` / `OWNER` | High at first run | Confirm via `?f=json` metadata at deploy time; fallback to Playwright property card. |
| Tracerfy API spend runaway | Low | First-run cap (`BACKFILL_MAX_LOOKUPS`); per-person cache prevents re-charging. |
| Apps Script quota (limits POSTs/day) | Low | Berkeley County volume is well under Apps Script's 20k/day execution limit. |
| VPS goes down | Low | systemd `Persistent=true` catches up missed hours; nightly SQLite backup; rolling 7-day window self-heals. |
| Owner-string parsing edge cases | Medium | All raw strings stored in `parcels.owner_raw`; we can re-parse historically by clearing `skipped_entity` rows and re-running. |
| Duplicate rows | Critical, prevented | 4-level UNIQUE constraints; final gate is `sheet_rows UNIQUE(case_number, person_key)`. |

## 9. Open items confirmed during deployment

- Exact ArcGIS service URL and field names for Berkeley County (discoverable via `/arcgis/rest/services` directory).
- Court site disclaimer button text (verified by inspecting the page).
- Whether SMTP-from-Gmail or Resend free tier is used for alerts (user choice at deploy).

## 10. Success criteria

- Bot runs every hour for 7 consecutive days without manual intervention.
- Zero duplicate rows in the sheet across that period.
- Mean per-run wall time < 10 minutes for steady state (post-backfill).
- A deliberately broken run (e.g., revoked Tracerfy key) produces exactly one alert email per hour.

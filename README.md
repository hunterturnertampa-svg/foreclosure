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

## First-time deploy verification

1. `python scripts/discover_arcgis_fields.py` — copy the query URL + field names into `.env`.
2. `python scripts/smoke_gis.py 123-45-67-001` (use any known Berkeley TMS) — confirm a parcel comes back with owner + address.
3. `python scripts/smoke_court.py` — confirm the scraper returns at least one case from the last 7 days. If selectors are wrong, edit `court_scraper.py` and re-run.
4. After all three pass, `systemctl enable --now foreclosure-bot.timer`.

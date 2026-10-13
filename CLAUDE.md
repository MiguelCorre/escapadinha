# CLAUDE.md

Travel-deals pipeline for the Portuguese market: collect → detect → render. No publishing in v1.
See README.md for usage and DECISIONS.md for rationale and the roadmap. Vocabulary: GLOSSARY.md.
v2 work is tracked as GitHub Issues (spec #1, tickets #2–#24): conventions in docs/agents/.

## Commands
- `uv run pytest`: all tests. `-m "not browser"` skips the Playwright render test.
- `uv run escapadinha <cmd>`: CLI (`init-db`, `collect`, `recheck`, `detect`, `stats`, `routes list|discover`, `photos fetch`,
  `render deals|guide`, `run`, `review`, `deal check|approve|reject|published`,
  `site build|preview|setup|deploy`, `design directions`,
  `store status|pull|push|restore|upload-archives|check`).
- Set `PYTHONIOENCODING=utf-8` in Git Bash on Windows so pt-PT output prints correctly.

## Rules
- **Never fabricate prices.** Observations come only from API payloads. No seed/demo data
  outside tests (tests use `tmp_path`). Every deal must trace to `price_observations.id`.
- Every deal caption and CTA slide carries `presentation.DISCLOSURE`. Tests assert this.
- `detector.py` stays pure (no I/O, no clock). Pass `now` in. Route rules (`RouteRules`) are
  passed in too; never read a global `direct_only` or nights range.
- Routes come from the `routes` table via `routes.py` (`active_routes`, `get_route`), never from
  config. config.yaml only holds per-kind defaults, overrides, exclusions, long-haul list, seed,
  discovery origins and `city_names`. Discovery (`discovery.py`) is pure; its downloads live in
  `collector/catalogue.py`. Routes are never deleted: they go `dormant` (D23).
- Plain SQL in `storage/db.py`. Schema changes bump `SCHEMA_VERSION`, update `schema.sql` (fresh
  installs) and add the ALTER steps to `MIGRATIONS` (existing DBs; a step may be a Python
  callable). Test the upgrade from real old schemas (`tests/fixtures/schema_v5.sql`, `schema_v7.sql`).
  Pipeline bookkeeping (e.g. last discovery time) goes in the `meta` key/value table.
- Observations are deduplicated (`dedup_key`); never assume one row per run. Use
  `observations_seen_since(run_id)` for a run's prices. Raw payloads live only in the run archive
  (`archive.py` via `ObjectStore`), never in the hot table.
- Objects go through `ctx.object_store` (R2 when the `R2_*` keys are set, else `data/objects/`);
  never write the bucket or `data/objects/` directly. Every `ObjectStore` implementation passes
  `tests/test_objects.py` (S3 runs on moto, no network). The database file is only uploaded via
  `storage/sync.py` (backup-API snapshot under the run lock), never the live file (D21).
- Captions must distinguish `found_date` (when a traveller saw the price) from `fetched_at`,
  and always name the arrival airport (remote ones in the headline).
- pt-PT formatting lives in `i18n_pt.py` (no OS locale). Times are shown in Europe/Lisbon.
- No scraping of booking sites or airlines (ToS and legal risk; see DECISIONS D13).
- Never publish a deal whose status is `expired` (recheck runs every collection). The website
  only shows deals a human approved; expired pages stay `noindex` without a booking link.
- Affiliate links only from `affiliate.PartnerLinksClient` (Travelpayouts API). Never build
  `marker=` URLs by hand, because Aviasales term 1.4 forbids it. Pick the Project with
  `affiliate.project_for("instagram"|"website")`; never read `project_id` directly (D19).
- Domain moves go through `site.base_url` + `site.legacy_hosts` and the Bulk Redirect in
  `docs/runbooks/brand-switch.md`; Pages `_redirects` can't match hosts. Page paths need a stable
  key in `SiteBuilder._write_routing` so renamed slugs get a 301 (`website/redirects.py`).
- Secrets only via `.env` (`Secrets` in `config.py`). Never commit `.env`, `data/`, `output/`.
- Update README.md, CLAUDE.md and DECISIONS.md in the same commit as a feature.

## Layout
- `src/escapadinha/collector/`: `TravelpayoutsSource` (+ `RateLimiter`), `runner.collect`, `catalogue.py`
- `src/escapadinha/discovery.py`: pure `Catalogue.from_payloads` + `discover` → `Found` routes with kind
- `src/escapadinha/routes.py`: `sync` (config → `routes` table), `apply_discovery`, `mark_dormant`,
  `all_routes`/`active_routes`/`get_route`
- `src/escapadinha/storage/objects.py`: `ObjectStore` + `LocalObjectStore` (`data/objects/`); `archive.py`: per-run raw archive
- `src/escapadinha/storage/s3.py`: `S3ObjectStore` (R2, conditional-write lock); `sync.py`: database
  pull/push, `run_session` (lock → pull → daily backup → push → unlock), restore, `store check`
- `src/escapadinha/detector.py`: daily-low `baseline` per route+month, `evaluate`, `detect_route`
- `src/escapadinha/pipeline.py`: DB wiring per CLI step (`run_discover`, `run_dormancy`,
  `run_missing_photos`, ...), plus review actions (`live_check`, `approve`, ...)
- `src/escapadinha/review.py`: status transitions; `web.py` + `templates/review.html.j2`: the local review page
- `src/escapadinha/renderer/templates/`: `base.html.j2` (tokens, fonts, scrims, components, fitText),
  `_ui.html.j2` (masthead, price block, dots, credit) + `deal/`, `guide/`
- `docs/design/`: `design-system.md` (the visual contract) + `tokens.json`, generated from
  `renderer/tokens.py` (`tokens.write_json()`; a test fails if stale or below WCAG AA). Fonts in
  `assets/fonts/` (OFL WOFF2), logos `assets/logo-light.svg` / `logo-dark.svg`.
- `src/escapadinha/captions/templates/`: `deal.txt.j2`, `guide.txt.j2`
- `content/guides/*.yaml`: hand-written guide content (`reviewed: true` after fact check)
- `src/escapadinha/website/`: static site builder (`build_site`), `redirects.py` (`_redirects`,
  `_headers`), `deploy.py` (wrangler), `templates/`
- `docs/runbooks/`: pt-PT step-by-step guides for things only Miguel can do (e.g. `brand-switch.md`)
- `src/escapadinha/design_directions/`: M2 visual directions (`build_directions` → `output/directions/`);
  palettes + fonts in `directions.py` (contrast computed by `contrast.py`), read-only data in `data.py`

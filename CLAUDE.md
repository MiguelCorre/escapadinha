# CLAUDE.md

Travel-deals pipeline for the Portuguese market: collect → detect → render. No publishing in v1.
See README.md for usage and DECISIONS.md for rationale and the roadmap.

## Commands
- `uv run pytest`: all tests. `-m "not browser"` skips the Playwright render test.
- `uv run escapadinha <cmd>`: CLI (`init-db`, `collect`, `detect`, `stats`, `photos fetch`, `render deals|guide`, `run`).
- Set `PYTHONIOENCODING=utf-8` in Git Bash on Windows so pt-PT output prints correctly.

## Rules
- **Never fabricate prices.** Observations come only from API payloads. No seed/demo data
  outside tests (tests use `tmp_path`). Every deal must trace to `price_observations.id`.
- Every deal caption and CTA slide carries `presentation.DISCLOSURE`. Tests assert this.
- `detector.py` stays pure (no I/O, no clock). Pass `now` in.
- Plain SQL in `storage/db.py`. Schema changes bump `SCHEMA_VERSION`, update `schema.sql` (fresh
  installs) and add the ALTER steps to `MIGRATIONS` (existing DBs). Test the upgrade.
- Captions must distinguish `found_date` (when a traveller saw the price) from `fetched_at`,
  and always name the arrival airport (remote ones in the headline).
- pt-PT formatting lives in `i18n_pt.py` (no OS locale). Times are shown in Europe/Lisbon.
- No scraping of booking sites or airlines (ToS and legal risk; see DECISIONS D13).
- Never publish a deal whose status is `expired` (recheck runs every collection).
- Affiliate links only from `affiliate.PartnerLinksClient` (Travelpayouts API). Never build
  `marker=` URLs by hand, because Aviasales term 1.4 forbids it.
- Secrets only via `.env` (`Secrets` in `config.py`). Never commit `.env`, `data/`, `output/`.
- Update README.md, CLAUDE.md and DECISIONS.md in the same commit as a feature.

## Layout
- `src/escapadinha/collector/`: `TravelpayoutsSource`, `runner.collect`
- `src/escapadinha/detector.py`: daily-low `baseline` per route+month, `evaluate`, `detect_route`
- `src/escapadinha/pipeline.py`: DB wiring per CLI step
- `src/escapadinha/renderer/templates/`: `base.html.j2` (tokens, scrim, logo, fitText) + `deal/`, `guide/`
- `src/escapadinha/captions/templates/`: `deal.txt.j2`, `guide.txt.j2`
- `content/guides/*.yaml`: hand-written guide content (`reviewed: true` after fact check)

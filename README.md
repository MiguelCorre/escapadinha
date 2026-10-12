# Escapadinha

Travel-deals automation for the Portuguese market (placeholder brand). It collects round-trip
flight prices from Lisbon and Porto, keeps a price history, flags prices well below each
route's own historical median, and renders Instagram carousel slides (1080×1350 PNG) with
pt-PT captions into `./output/<date>/` **for manual review. v1 does not publish anything.**

**Integrity rule:** every price shown comes from a stored API observation (`price_observations`)
with its source, `fetched_at` timestamp and the verbatim API item (`raw_json`). Nothing is
estimated or invented. Each rendered deal carries a `meta.json` pointing back to that row.

## Pipeline

```
Travelpayouts API ──collect──▶ SQLite (price_observations)
                                   │
                                detect  (median of the last 90 days, threshold 30%)
                                   ▼
                              deals (status: new)
                                   │
                         render deals ──▶ output/<date>/deal-LIS-LON-12/
                                            slide_01..03.png · caption.txt · meta.json
```

| Module | Role |
|---|---|
| `collector/` | `TravelpayoutsSource` (v3 `prices_for_dates`), `runner.collect` (route × month loop) |
| `storage/` | `schema.sql` + plain-SQL repository functions in `db.py` |
| `detector.py` | Pure functions: `baseline`, `evaluate`, `detect_route` |
| `photos.py` | Pixabay search + download, credit stored in `photos` |
| `renderer/` | Jinja HTML/CSS → Playwright Chromium → PNG |
| `captions/` | pt-PT caption templates (price, dates, timestamp, disclosure) |
| `pipeline.py` | Wires the DB to each step; `cli.py` exposes them |

## Setup

Requirements: Windows/macOS/Linux with [uv](https://docs.astral.sh/uv/). uv installs Python 3.14.

```bash
uv sync
uv run playwright install chromium
cp .env.example .env        # then fill in the keys below
uv run escapadinha init-db
```

Keys (`.env`, never committed):

| Variable | Where |
|---|---|
| `TRAVELPAYOUTS_TOKEN` | travelpayouts.com → sign up → *Profile → API token* |
| `TRAVELPAYOUTS_MARKER` | Your partner marker (numeric). Appended to Aviasales links as `marker=` |
| `PIXABAY_API_KEY` | pixabay.com/api/docs: free key, shown on that page once you're logged in |

In the Travelpayouts dashboard, join the **Aviasales** program and check under its
traffic rules that **Instagram/social media** traffic is allowed before posting.

## Running each step

```bash
uv run escapadinha collect                 # ~30 API calls: 10 routes × 3 departure months
uv run escapadinha detect                  # evaluates the latest run; prints a per-route table
uv run escapadinha stats LIS-LON           # history size, min/max, current median
uv run escapadinha photos fetch            # one Pixabay photo per destination (cached)
uv run escapadinha photos fetch --dest LON --force --pick 2   # swap a photo you don't like
uv run escapadinha render deals            # renders deals with status 'new' → 'rendered'
uv run escapadinha render deals --deal-id 12
uv run escapadinha render guide voos-baratos-dicas
uv run escapadinha run                     # collect → detect → render (what the scheduler runs)
```

Output for review lives in `output/<YYYY-MM-DD>/`:
- `deal-<ORIG>-<DEST>-<id>/slide_01.png … slide_03.png`: cover, details, CTA + disclosure
- `caption.txt`: pt-PT caption, ready to paste
- `meta.json`: observation id, run id, source, `fetched_at`, median, sample size, affiliate URL, photo credit

## Configuration (`config.yaml`)

- `routes`: origin/destination IATA (city codes like `LON`, `PAR` work), `city_pt` for display,
  and an optional `price_cap_eur`.
- `collector`: `months_ahead` (3 = this month + 2), `min_nights`/`max_nights` (2–10), currency.
- `detector`:
  - `threshold: 0.30` flags a price when `price ≤ median × (1 − 0.30)`.
  - `lookback_days: 90` is the history window.
  - `min_samples: 20` and `min_history_days: 7` decide when history is mature enough to trust.
  - `dedupe_days: 7` stops the same trip being re-flagged unless it gets cheaper.
  - `max_deals_per_route: 1` caps deals per route per run.

### How "too little history" is handled
The median counts each offer at most once per day, because the source is a cache and
returns the same offers on every run. Until a route has `min_samples` samples spread over
`min_history_days`, `detect` reports **insufficient_history** and flags nothing. The one
exception is a route with an explicit `price_cap_eur`: offers at or below the cap are
flagged as `rule = price_cap`, and the caption then makes no "% below" claim. A fresh
install therefore needs about a week of scheduled collection before median-based deals appear.

## Scheduling (Windows Task Scheduler)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1              # 08:00, 14:00, 20:00
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Times 07:30,19:30
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister
```
Each run appends to `logs/run-<date>.log`.

## Guides ("guia rápido")

Add `content/guides/<slug>.yaml` with a title, 3–8 tips, CTA, caption and hashtags (see the
sample). Guides are hand-written. Set `reviewed: true` after checking the facts; the CLI
warns until then. `photo_destination` picks a cached photo (for example `LIS`; add its
query under `photos.queries` and run `photos fetch --dest LIS`).

## Fonts and branding

All branding is a placeholder: `assets/logo.svg`, the colour tokens at the top of
`renderer/templates/base.html.j2`, and the `brand` block in `config.yaml`. Headlines use
Bahnschrift or Segoe UI Black (Windows system fonts). Drop an OFL display font at
`assets/fonts/display.ttf` and it is used automatically.

## Tests

```bash
uv run pytest               # all tests (the 'browser' test renders real PNGs, ~3 s)
uv run pytest -m "not browser"
```
`tests/fixtures/prices_for_dates_LIS_LON.json` is a **synthetic** fixture shaped like the API
response. Replace it with a recorded real response once you have a token.

## Data sources and terms

- **Travelpayouts / Aviasales Data API**: a cache of prices users found recently (not live).
  The limit is 600 req/min on v3 endpoints. Captions always state when and where the price
  was found and that prices change.
- **Pixabay**: free commercial use under the Pixabay Content License. The API forbids
  hotlinking, so photos are downloaded once and cached, and every caption credits the
  contributor. Standard keys get `largeImageURL` (max 1280 px, slightly upscaled to
  1080×1350). Approved full API access unlocks `fullHDURL`, which is used automatically.
- Affiliate disclosure ("Publicidade · … links de afiliado …") appears on every deal caption
  and on the CTA slide.

See [DECISIONS.md](DECISIONS.md) for why these were chosen and the v2/v3 roadmap.

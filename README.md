# Escapadinha

Travel-deals automation for the Portuguese market (placeholder brand). It collects round-trip
flight prices from Lisbon and Porto, keeps a price history, flags prices well below each
route's own historical median, and renders Instagram carousel slides (1080×1350 PNG) with
pt-PT captions into `./output/<date>/` **for manual review. v1 does not publish anything.**

**Integrity rule:** every price shown comes from a stored API observation (`price_observations`)
with its source, `fetched_at` timestamp, the day a traveller found it (`found_date`) and the
verbatim API item (`raw_json`). Nothing is
estimated or invented. Each rendered deal carries a `meta.json` pointing back to that row.

## Pipeline

```
Travelpayouts API ──collect──▶ SQLite (price_observations)       (market=pt, every 2 h)
                                   │
                               recheck  open deals: same trip still ≤ price, fresh, direct?
                                   │            no → status expired + EXPIRADO.txt
                                detect  (fresh direct price ≥30% below the month's typical low)
                                   ▼
                              deals (status: new)
                                   │
                         render deals ──▶ output/<date>/deal-LIS-LON-12/
                                            slide_01..03.png · caption.txt · meta.json
```

| Module | Role |
|---|---|
| `collector/` | `TravelpayoutsSource` (v3 `prices_for_dates`), `runner.collect` (route × month loop) |
| `routes.py` | Routes as data: `sync` (config → `routes` table), `active_routes`, effective rules per route |
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
uv run escapadinha routes list             # every route: kind, rules, status, last observed (pt-PT)
uv run escapadinha collect                 # ~30 API calls: 10 active routes × 3 departure months
uv run escapadinha recheck                 # re-verifies open deals against the latest run
uv run escapadinha detect                  # evaluates the latest run; prints a per-route table
uv run escapadinha stats LIS-LON           # history size, min/max, current median
uv run escapadinha photos fetch            # one Pixabay photo per destination (cached)
uv run escapadinha photos fetch --dest LON --force --pick 2   # swap a photo you don't like
uv run escapadinha render deals            # renders deals with status 'new' → 'rendered'
uv run escapadinha render deals --deal-id 12
uv run escapadinha render guide voos-baratos-dicas
uv run escapadinha run                     # collect → recheck → detect → render (the scheduler)
```

Output for review lives in `output/<YYYY-MM-DD>/`:
- `deal-<ORIG>-<DEST>-<id>/slide_01.png … slide_03.png`: cover, details, CTA + disclosure
- `caption.txt`: pt-PT caption, ready to paste
- `meta.json`: observation id, run id, source, `fetched_at`, `found_date`, typical low, tracked
  `affiliate_url` (or `affiliate_error`), raw `booking_url`, photo credit

## Configuration (`config.yaml`)

- `routes`: routes live in the database (`routes` table, `escapadinha routes list`); config
  only shapes them (DECISIONS D17):
  - `kinds`: default rules per kind. `europe` and `domestic` (the "Ilhas"): nonstop both ways,
    2–10 nights. `long_haul`: up to 1 stop each way, 7–21 nights. `direct_only` wins over
    `max_transfers` (stops per direction). Offers outside a route's rules are not collected
    (nights), are never deals and never count towards its typical low.
  - `overrides`: per-route exceptions, e.g. `"LIS-LON": { max_nights: 7 }`, plus an optional
    `price_cap_eur`. Removing an override restores the kind default on the next command.
  - `exclusions`: route keys (`LIS-LON`) or destinations (`LON`) that are never collected.
  - `long_haul`: curated long-haul destinations (`destination`, `city_pt`, `origins`), added as
    `long_haul` routes.
  - `seed`: the 10 original routes (city codes like `LON`, `PAR` work), inserted once into an
    empty table. Changing it later has no effect; discovery (#5) will add routes.
- `collector`: `months_ahead` (3 = this month + 2), currency. Nights come from each route's rules.
- `detector`:
  - `threshold: 0.30` flags a price when `price ≤ typical_low × (1 − 0.30)`.
  - `lookback_days: 90` is how far back daily lows count.
  - `min_baseline_days: 4` is how many days with a low are needed before a month's typical low is trusted.
  - `max_offer_age_days: 3` defines the freshness window. Prices travellers found in the last
    3 days are candidates, and older days form the baseline.
  - `dedupe_days: 7` stops the same trip being re-flagged unless it gets cheaper.
  - `max_deals_per_route: 1` caps deals per route per run (biggest discount first).
- `collector.market: pt` and `collector.booking_base: https://www.aviasales.pt` use prices from
  the Portuguese market, and links open in euros with a 24h clock. Aviasales' UI is English/Russian only.

### Deals expire
The source is a cache and prices move. On the first real day a 60 € deal was 70 € two hours
later. Every run rechecks open deals (`new`, `rendered`, `approved`) against the newest prices.
A deal stays valid only while the same trip is still offered at or below the deal price,
found within `max_offer_age_days`, and within the route's rules (nonstop where `direct_only`,
at most `max_transfers` stops per direction, nights range). Otherwise it becomes
`expired`, gets an `expired_reason`, and its output folder gets `EXPIRADO.txt` ("NÃO PUBLICAR").
A route with no data in a run is skipped, so an API hiccup expires nothing.

### What counts as a deal
A deal is a fresh price well below the route's **typical lowest price for the same departure
month**: the median of daily lows, where each day's low is the cheapest price travellers found
that day.

Comparing against all fares would be wrong. A route's cheapest dates are always far below the
median of all fares, so that rule flags almost every route on every run. On the first real data
it flagged 9 of 10 routes.

The source cache records when each price was found and covers about a week, so baselines
exist from the **first run**. Until a month has `min_baseline_days` daily lows, `detect` reports
**warming up** and flags nothing. The one exception is a route with an explicit
`price_cap_eur` (`rule = price_cap`); the caption then makes no "% below" claim.

Every deal names its arrival airport. Remote airports (for example Paris-**Beauvais**,
Milan-**Bérgamo**) also appear in the headline: "Porto → Paris (Beauvais)".

## Approval queue

```bash
uv run escapadinha review            # opens http://127.0.0.1:8765 (local only; Ctrl+C to stop)
```

The page (in Portuguese) has four tabs: **Por rever**, **Aprovados**, **Publicados** and **Fechados**
(expired or rejected). Each deal shows its three slides, the caption with a copy button, the
affiliate link, and the facts behind it: price, typical low, discount, arrival airport,
found/checked dates and the last recheck.

- **Verificar preço agora** fetches that route and month from the API now and rechecks the deal.
- **Aprovar** runs that same live check first. If the price moved, the deal expires instead of
  being approved. A deal without an affiliate link can't be approved.
- **Rejeitar** (optional note) and **Marcar como publicado** (optional post URL) record the decision.
  Publishing to Instagram is still manual.
- Approved deals keep being rechecked every 2 h. If the price moves before you post, the deal
  expires and the page tells you.

Live checks are stored as `live_check` runs, so their prices are traceable, but they never count
as the latest full collection. The CLI applies the same rules:

```bash
uv run escapadinha deal check 12
uv run escapadinha deal approve 12 --note "bom deal"
uv run escapadinha deal reject 12 --note "datas fracas"
uv run escapadinha deal published 12 --url https://www.instagram.com/p/...
```

Status flow: `new → rendered → approved → published`. `rejected` and `expired` are final;
`expired` is only set by price checks.

## Public website

The website is static and generated from the database into `site/` (git-ignored). It's the
Instagram "link na bio". The brand is **Ponto Nómada** (Instagram still `@ondestaanocas` until renamed) and the site is hosted on
Cloudflare Pages. It's **live at https://ondestaanocas.pages.dev** (since 2026-10-13) until a .pt domain is connected.

```bash
uv run escapadinha site build     # generate ./site
uv run escapadinha site preview   # http://127.0.0.1:8766
uv run escapadinha site setup     # one-time: create the Cloudflare Pages project (REST API)
uv run escapadinha site deploy    # upload if the content changed (--force to always upload)
```

| Page | What it shows |
|---|---|
| `/` | Live deals (approved or published, not expired), routes, reviewed guides |
| `/promos/<id>-<origem>-<destino>/` | Slides, details, "Ver voo e reservar" (tracked link, `rel="sponsored nofollow"`) |
| `/voos/<origem>-<destino>/` | Live deals, typical low per departure month (real data), recent expired deals |
| `/guias/<slug>/` | Only guides with `reviewed: true` |
| `/sobre/`, `/privacidade/`, `404.html`, `sitemap.xml`, `robots.txt` | |

- **Only approved deals go public.** A deal that expires after approval keeps its page, so
  shared links don't break. That page says the deal expired, drops the booking button, is
  marked `noindex` and is left out of the sitemap. Deals that expired or were rejected before
  approval never appear.
- **Images:** slides become WebP (1080 px), plus a 540 px thumbnail and a JPEG for Open Graph.
- **Run integration:** `escapadinha run` rebuilds the site every time. It deploys only when
  `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are set and the content changed (the
  footer's "Atualizado a" timestamp is ignored). Deploys use `npx wrangler@<site.wrangler_version>`,
  so Node.js is required.
- **To review before going live:** the "Como funciona" and "Privacidade" texts.

## Affiliate links

Each deal gets **one tracked link** from the Travelpayouts partner links API, created at render
time for the Project in `config.yaml` (`affiliate.project_id`, currently 584711 =
instagram.com/ondestaanocas). The link is short, like `https://aviasales.tpo.lu/UQWMX2Ed`, and
carries `sub_id=deal-<id>` so the dashboard shows stats per deal. It's stored on the deal and
reused on later renders.

If conversion fails, the deal keeps **no** link. `affiliate_error` explains why, the CLI warns,
and the next render retries. There is deliberately no fallback to a hand-built `marker=` URL,
because Aviasales program term 1.4 only allows network tools.

## Scheduling (Windows Task Scheduler)

```powershell
powershell -ExecutionPolicy Bypass -File scripts
egister-task.ps1                # every 2 h, all day
powershell -ExecutionPolicy Bypass -File scripts
egister-task.ps1 -EveryHours 1
powershell -ExecutionPolicy Bypass -File scripts
egister-task.ps1 -Unregister
```
Each run takes about 1 minute and uses 30 API calls. Runs missed while the PC sleeps start
when it wakes. Output is appended to `logs/run-<date>.log`, ending with `---- exit N ----`.

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
- `tests/fixtures/prices_for_dates_LIS_LON.json` is **synthetic** and covers the edge cases.
- `recorded_prices_for_dates_LIS_LON_2026-11.json` is a real response recorded on 2026-10-12.

## Data sources and terms

- **Travelpayouts / Aviasales Data API**: a cache of prices users found recently (not live).
  The limit is 600 req/min on v3 endpoints. Each item's link carries `search_date`, the day a
  user found the price, which can be several days old. Captions state both that date and when
  we checked it, and that prices change. Times are UTC, so trip dates are taken from the link's
  local dates.
- **Pixabay**: free commercial use under the Pixabay Content License. The API forbids
  hotlinking, so photos are downloaded once and cached, and every caption credits the
  contributor. Standard keys get `largeImageURL` (max 1280 px, slightly upscaled to
  1080×1350). Approved full API access unlocks `fullHDURL`, which is used automatically.
- Affiliate disclosure ("Publicidade · … links de afiliado …") appears on every deal caption
  and on the CTA slide.

See [DECISIONS.md](DECISIONS.md) for why these were chosen and the v2/v3 roadmap, and
[LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) for what must happen before the first public post.

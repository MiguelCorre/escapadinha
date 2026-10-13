# Escapadinha

Travel-deals automation for the Portuguese market (placeholder brand). It collects round-trip
flight prices for every direct route from Lisbon, Porto, Faro, Madeira, Ponta Delgada and
Terceira (discovered automatically) plus ~20 long-haul destinations, keeps a price history, flags prices well below each
route's own historical median, and renders Instagram carousel slides (1080×1350 PNG) with
pt-PT captions into `./output/<date>/` **for manual review. v1 does not publish anything.**

**Integrity rule:** every price shown comes from a stored API observation (`price_observations`)
with its source, first `fetched_at` timestamp and the day a traveller found it (`found_date`).
The verbatim API responses of each run are archived as one gzip JSON object (`fetch_runs.archive_key`).
Nothing is estimated or invented. Each rendered deal carries a `meta.json` pointing back to that
row, its first run and the archive object: price → deal → observation → run → raw payload.

## Pipeline

```
Travelpayouts catalogues ──routes discover──▶ routes table (monthly; dormant after 30 days without prices)
                                                   │ active routes
Travelpayouts API ──collect──▶ SQLite (price_observations, one row per offer)  (market=pt, every 2 h)
                       └──────▶ data/objects/archive/runs/<run>.json.gz (raw responses)
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
| `collector/` | `TravelpayoutsSource` (v3 `prices_for_dates`, rate-limited), `runner.collect` (route × month loop), `catalogue.py` (discovery downloads) |
| `discovery.py` | Pure: catalogues + supplements → direct routes with kind and pt-PT name |
| `routes.py` | Routes as data: `sync` (config → `routes` table), `apply_discovery`, `mark_dormant`, `active_routes`, effective rules per route |
| `storage/` | `schema.sql` + plain-SQL repository functions in `db.py`; `objects.py`/`s3.py` (object store: local dir or R2); `sync.py` (database pull/push, run lock, daily backups) |
| `detector.py` | Pure functions: `baseline`, `evaluate`, `detect_route` |
| `photos.py` | Pixabay search + download, credit stored in `photos` |
| `renderer/` | Jinja HTML/CSS → Playwright Chromium → PNG; `tokens.py` = design-system tokens |
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
| `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | Optional. Cloudflare → R2 → *Manage R2 API Tokens* (Object Read & Write on the bucket only). All four set = database and archives in R2 (see [Database in R2](#database-in-cloudflare-r2-decisions-d21)); any missing = everything stays under `data/` |

In the Travelpayouts dashboard, join the **Aviasales** program and check under its
traffic rules that **Instagram/social media** traffic is allowed before posting.

## Running each step

```bash
uv run escapadinha routes discover         # find direct routes from the 6 airports (+ photos for new destinations)
uv run escapadinha routes discover --dry-run --no-photos   # show what would change, store nothing
uv run escapadinha routes list             # every route + active/dormant counts per origin (pt-PT)
uv run escapadinha collect                 # active routes × 3 departure months (~1080 calls at 360 routes)
uv run escapadinha recheck                 # re-verifies open deals against the latest run
uv run escapadinha detect                  # evaluates the latest run; prints a per-route table
uv run escapadinha stats LIS-LON           # history size, min/max, current median
uv run escapadinha photos fetch            # one Pixabay photo per destination (cached)
uv run escapadinha photos fetch --dest LON --force --pick 2   # swap a photo you don't like
uv run escapadinha render deals            # renders deals with status 'new' → 'rendered'
uv run escapadinha render deals --deal-id 12
uv run escapadinha render guide voos-baratos-dicas
uv run escapadinha run                     # (monthly discovery) → collect → recheck → detect → render (the scheduler)
uv run escapadinha store status            # R2 only: bucket database, lock, backups, local copy
uv run escapadinha store pull              # R2 only: bucket database → data/escapadinha.db
uv run escapadinha store push              # R2 only: data/escapadinha.db → bucket (takes the lock)
```

### Routes are discovered (DECISIONS D23)
`routes discover` (and `run`, when the last discovery is 30+ days old; the time is kept in the
`meta` table) builds the route list from Travelpayouts' own data, never from scraping:
- the static catalogue `data/routes.json` (airline routes; rows with `transfers: 0` departing
  LIS, OPO, FAO, FNC, PDL or TER), arrival airports mapped to city codes with
  `data/airports.json`, names from `data/pt/cities.json` (Portuguese, else English);
- two supplements with the token, because the static catalogue is years out of date: the popular
  directions per origin (`v1/city-directions`, nonstop ones only) and the nonstop fares found
  recently from each origin (`v3/prices_for_dates` with no destination, `direct=true`, one call
  per departure month). Only destinations are used; these prices are never stored;
- the curated `routes.long_haul` list (LIS and OPO).

Kind: Portugal → `domestic` ("Portugal"), Europe and North Africa → `europe`, anything else only
when it is on the long-haul list for that origin. Existing routes keep their name, kind and
rules; discovery only fills in airports and the English name. `routes.city_names` fixes
catalogue names (e.g. `HAM: Hamburgo`; the catalogue says "Finkenwerder").

**Dormancy:** after each collection that didn't fail completely, an active route with no price
seen for `dormant_after_days` (30; counted from its newest sighting, or from `discovered_at` if
it never had one) becomes `adormecida` and is not collected. The next discovery that finds it
again reactivates it; the following collection is its probe: with prices it stays, without it
goes back to sleep. Nothing is deleted. Excluded routes are left alone.

**Photos:** every destination of an active route gets a Pixabay photo automatically (query:
`photos.queries` override, else the English city name), at most `photos.max_per_run` (40) per
discovery or run, so ~160 destinations take four runs. Failures are retried next time.

**Budget:** a run makes one request per active route and departure month. On 2026-10-13 that
was 360 routes × 3 = 1080 requests in 5 min 40 s (≈190/min, latency-bound). The source allows
600/min; `collector.requests_per_minute: 550` caps it client-side and a 429 still waits and retries.
At 12 runs/day that's ~13k requests/day and ~70 runner-minutes/day (see D23 for GitHub Actions).

Output for review lives in `output/<YYYY-MM-DD>/`:
- `deal-<ORIG>-<DEST>-<id>/slide_01.png … slide_03.png`: cover, details, CTA + disclosure
- `caption.txt`: pt-PT caption, ready to paste
- `meta.json`: observation id, run id (first run that saw the price), `archive_key` (its raw
  responses), source, `fetched_at`, `found_date`, typical low, tracked `affiliate_url` (or
  `affiliate_error`), raw `booking_url`, photo credit

### Observations are stored once (DECISIONS D18)
The API returns the same cached offers run after run (at 10 routes, 6644 rows held 606 distinct
offers). An offer is identified by source, route, departure/return timestamps, airline, flight
number, price and found date. A repeat updates `last_seen_at`, `last_run_id` and `seen_count`
(once per run); `run_id` and `fetched_at` keep the first sighting. `collect` prints new vs.
repeated offers, `stats` the seen counts. "The prices of the latest run" are the offers whose
`last_run_id` is that run or later (a live check counts as a sighting).

Raw responses leave the database: each run (including live checks) writes
`archive/runs/<run id>.json.gz` through the `ObjectStore` interface (`storage/objects.py`:
get/put/list/delete/lock). Without R2 keys the store is `data/objects/`; with them, the R2 bucket.
Upgrading from schema v6 collapses duplicates (rows with a deal keep their id), parks the old
`raw_json` values and archives them per run on the next command (`reconstructed: true`), then
VACUUMs. On the real database: 9.4 MB → 0.65 MB plus 0.8 MB of archives.

## Configuration (`config.yaml`)

- `routes`: routes live in the database (`routes` table, `escapadinha routes list`); config
  only shapes them (DECISIONS D17):
  - `kinds`: default rules per kind. `europe` and `domestic` (the "Portugal" category): nonstop both ways,
    2–10 nights. `long_haul`: up to 1 stop each way, 7–21 nights. `direct_only` wins over
    `max_transfers` (stops per direction). Offers outside a route's rules are not collected
    (nights), are never deals and never count towards its typical low.
  - `overrides`: per-route exceptions, e.g. `"LIS-LON": { max_nights: 7 }`, plus an optional
    `price_cap_eur`. Removing an override restores the kind default on the next command.
  - `exclusions`: route keys (`LIS-LON`) or destinations (`LON`) that are never discovered nor
    collected (now `MOW`, `LED`, `IEV`, `MSQ`: the old catalogue still lists them).
  - `long_haul`: 20 curated long-haul destinations (`destination`, `city_pt`, `origins`
    default LIS and OPO), added as `long_haul` routes.
  - `origins`, `discover_every_days` (30), `dormant_after_days` (30), `city_names`: discovery,
    see "Routes are discovered".
  - `seed`: the 10 original routes (city codes like `LON`, `PAR` work), inserted once into an
    empty table. Changing it later has no effect; discovery adds the rest.
- `collector`: `months_ahead` (3 = this month + 2), currency, `requests_per_minute` (550).
  Nights come from each route's rules.
- `photos`: `queries` (Pixabay search per destination code) and `max_per_run` (40).
- `origins_pt`: origin names in captions (LIS Lisboa … FNC Madeira, PDL Ponta Delgada, TER Terceira).
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
Cloudflare Pages. It's **live at https://ondestaanocas.pages.dev** (since 2026-10-13) until the
final domain **pontonomada.pt** (D19, registered 2026-10-13 at PTisp) is connected. The switch is guided in
[docs/runbooks/brand-switch.md](docs/runbooks/brand-switch.md) (pt-PT).

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
| `_redirects`, `_headers` | Cloudflare Pages rules (not pages), see "Domain and redirects" |

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

### Domain and redirects

- `site.base_url` is the one switch: canonical URLs, Open Graph, sitemap and robots.txt use it.
  `site.domain` names the final domain; `site build` reminds you while `base_url` isn't on it.
- **Old host → new domain** is a Cloudflare **Bulk Redirect** (account level, free, set up once
  by hand), because Pages `_redirects` can't match on the host (D19). It keeps path and query,
  so every old link opens the same page on the new domain.
- **`_headers`** (generated): `X-Robots-Tag: noindex` on `site.legacy_hosts` other than the
  `base_url` host, and on per-deployment `<hash>.<project>.pages.dev` URLs.
- **`_redirects`** (generated, 301): `site.redirects` from config, every older path of a page whose
  slug changed (history in `data/site_paths.json`), and short `/promos/<id>` links. A rule never
  uses a path that is a page now (Pages applies redirects before files); skipped config rules are
  printed by `site build`.

## Visual directions (M2, issue #11)

Three candidate looks for Ponto Nómada, each as a home page and a promotion page built from
the real database and the cached photos. Miguel chose **A · Caderno de Viagem** (DECISIONS D20); the pages stay as the reference for #12.

```bash
uv run escapadinha design directions               # writes output/directions/ (7 pages + photos)
uv run escapadinha design directions --deal-id 2   # choose the promotion shown on the promo pages
```

Open `output/directions/index.html` in a browser (double-click works; fonts load from Google
Fonts, so be online). For dark mode, switch the OS theme or use the "Tema" button on each page.
To view on a phone on the same network:
`uv run python -m http.server 8781 --directory output/directions --bind 0.0.0.0`.

| Folder | Direction |
|---|---|
| `a-caderno/` | A · Caderno de Viagem: editorial magazine (Fraunces + Source Serif 4) |
| `b-por-do-sol/` | B · Pôr do Sol: warm sunset/sea, closest to the brand sketch (DM Serif Display + DM Sans) |
| `c-quadro/` | C · Quadro de Partidas: airport departure board (Space Grotesk + JetBrains Mono) |

- **Real data only.** The DB is opened read-only. Prices are promotions (approved, published
  or expired; never new/rendered/rejected) and *preços baixos*: direct offers from the latest
  run, found inside the freshness window, below the route's typical low for that month.
  Expired promotions are marked and have no booking link. Every page carries the disclosure.
- **Palettes live in Python** (`design_directions/directions.py`) and are emitted as CSS
  tokens, so the WCAG contrast table on each page is computed from the same values. Body text
  pairs must reach 4.5:1 in light and dark (tests enforce it); text on photos is checked on
  its scrim over a white pixel (worst case).

## Affiliate links

Each deal gets **one tracked link** from the Travelpayouts partner links API, created at render
time for the **Instagram** Project (`affiliate.projects.instagram`, currently 584711 =
instagram.com/ondestaanocas; the older `affiliate.project_id` key still works). The link is short,
like `https://aviasales.tpo.lu/UQWMX2Ed`, and carries `sub_id=deal-<id>` so the dashboard shows
stats per deal. It's stored on the deal and reused on later renders.

The **website** uses its own Project once `affiliate.projects.website` is set (until then it shows
the deal's link). Its links are created at `site build` with `sub_id=site-deal-<id>` and cached
per Project in `data/site_links.json`. A website link that fails falls back to the deal's own
tracked link and is retried on the next build. A Project's URL can't change once it joined a
program, so a new domain or handle means a new Project (runbook steps 8–9).

If conversion fails, the deal keeps **no** link. `affiliate_error` explains why, the CLI warns,
and the next render retries. There is deliberately no fallback to a hand-built `marker=` URL,
because Aviasales program term 1.4 only allows network tools.

## Database in Cloudflare R2 (DECISIONS D21)

With the four `R2_*` keys in `.env`, the bucket holds everything a run needs between runs, so
any machine (later GitHub Actions) can run the pipeline. Without them nothing changes: the
database is `data/escapadinha.db` and objects live under `data/objects/`.

| Object | What |
|---|---|
| `db/escapadinha.db` | The database: a consistent copy made with the SQLite backup API, integrity-checked |
| `db/escapadinha.json` | Its metadata: `generation` (+1 per push), sha256, `pushed_at`, `pushed_by`, last run id |
| `archive/runs/<run>.json.gz` | Raw API responses per run (D18), written straight to the bucket |
| `backups/<YYYY-MM-DD>/escapadinha.db` | The database before the first run of that Lisbon day |
| `locks/run` | The run lock: `{owner, expires_at}` |

`escapadinha run` then does: **lock → pull → daily backup → collect … deploy → push → unlock.**
- The lock is created with a conditional write (`If-None-Match: *`), so only one run gets it. A
  run that finds it held prints `Another run is in progress (…): nothing done.` and exits 0
  without touching anything. A lock older than 60 minutes (a crashed run) is taken over with
  `If-Match`, and a run only deletes the lock while it still names it.
- The database is pushed even when a step fails halfway: what was collected is in it and its
  archives are already in the bucket. A copy that fails `PRAGMA quick_check` is never pushed
  or installed.
- `data/escapadinha.db.sync.json` remembers which generation the local file came from. If the
  local file changed on top of the bucket's current generation, the run uses it (and pushes it);
  if it changed on top of an older one, the run keeps it as `data/escapadinha.db.local-<time>`
  and uses the bucket's.

**On your PC** (review, `deal approve`, stats): `store pull` before, `store push` after.
- `store push` takes the run lock, so it refuses while a run is in progress. It also refuses
  when the bucket moved on since your pull (`The bucket has a newer database: generation N …`);
  pull first, or `--force` to overwrite.
- `store pull` refuses to drop local changes you did not push; `--force` discards them and
  keeps a `.local-<time>` copy.
- `store status` shows the bucket's generation, the lock, the backups and your local copy.

**First time** (after filling `.env`):
```bash
uv run escapadinha store check             # round trip with throwaway keys: put/get/list/delete + lock
uv run escapadinha store push              # uploads this PC's database as generation 1
uv run escapadinha store upload-archives   # raw archives from data/objects/ the bucket lacks
uv run escapadinha store status
uv run escapadinha run                     # pulls, backs up, collects, pushes
```

**Lifecycle rule (set once in the dashboard):** R2 → bucket → *Settings* → *Object lifecycle
rules* → add rule, prefix `backups/`, *Delete objects* after **30 days**. Nothing else in the
bucket expires.

**Restore from a backup:**
1. Stop the scheduled runs (`powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1
   -Unregister`) and check that `uv run escapadinha store status` shows `lock: free`.
2. `uv run escapadinha store restore 2026-10-13` (dates are listed by `store status`). The current
   local file is kept as `data/escapadinha.db.local-<time>`.
3. Check it (`uv run escapadinha stats LIS-LON`, `uv run escapadinha review`), then
   `uv run escapadinha store push`. It becomes the next generation; runs pull it from then on.
4. Register the schedule again (`scripts\register-task.ps1`, see below).

Without the CLI: download `backups/<date>/escapadinha.db` from the R2 dashboard to
`data/escapadinha.db`, then `uv run escapadinha store push --force`.

## Scheduling (Windows Task Scheduler)

```powershell
powershell -ExecutionPolicy Bypass -File scripts
egister-task.ps1                # every 2 h, all day
powershell -ExecutionPolicy Bypass -File scripts
egister-task.ps1 -EveryHours 1
powershell -ExecutionPolicy Bypass -File scripts
egister-task.ps1 -Unregister
```
Each run takes about 6 minutes and makes one API call per active route and month (1080 at 360
routes; plus ~25 once a month for discovery). Runs missed while the PC sleeps start
when it wakes. Output is appended to `logs/run-<date>.log`, ending with `---- exit N ----`.

## Guides ("guia rápido")

Add `content/guides/<slug>.yaml` with a title, 3–8 tips, CTA, caption and hashtags (see the
sample). Guides are hand-written. Set `reviewed: true` after checking the facts; the CLI
warns until then. `photo_destination` picks a cached photo (for example `LIS`; add its
query under `photos.queries` and run `photos fetch --dest LIS`).

## Fonts and branding

The look is the **design system** in [docs/design/design-system.md](docs/design/design-system.md)
(direction A "Caderno de Viagem", DECISIONS D20/D22): type, colour tokens (light/dark, contrast table),
spacing, components (price block, card, tag, notice, …), photo treatment and tone of voice.

- **Tokens:** values live in `src/escapadinha/renderer/tokens.py`; `docs/design/tokens.json` is the
  Tailwind-ready copy for the website. After changing a token, regenerate it:
  `uv run python -c "from escapadinha.renderer import tokens; tokens.write_json()"` (a test fails
  if it is stale or a colour pair drops below WCAG AA).
- **Fonts:** Fraunces (headlines, prices) and Source Serif 4 (text), SIL OFL 1.1, self-hosted as
  WOFF2 in `assets/fonts/` with their licences. The slides inline them, so rendering works offline.
- **Logo (provisional):** `assets/logo-light.svg` (on paper) and `assets/logo-dark.svg` (on photos
  and dark slides). The designer's logo (M6) replaces both files.
- **Slides:** deal = cover (photo + paper card with price, dates, "encontrado a"), ficha (details,
  found vs checked), CTA (dark, disclosure). Guides: photo cover, paper tip pages, dark CTA.
- The `brand` block in `config.yaml` sets the name, tagline and handle.

## Tests

```bash
uv run pytest               # all tests (the 'browser' test renders real PNGs, ~3 s)
uv run pytest -m "not browser"
```
- `tests/fixtures/prices_for_dates_LIS_LON.json` is **synthetic** and covers the edge cases.
- `recorded_prices_for_dates_LIS_LON_2026-11.json` is a real response recorded on 2026-10-12.
- The object store contract (`test_objects.py`) and the database sync (`test_sync.py`) run against
  both the local store and `S3ObjectStore` on moto's in-process S3 mock: no network, no bucket.
- `fixtures/discovery/` holds real catalogue and supplement payloads recorded on 2026-10-13,
  trimmed to the rows the tests need (`RECORDED.txt` lists the URLs and what was kept).
- `fixtures/schema_v5.sql` and `schema_v7.sql` are older schemas, to test the upgrades.

## Data sources and terms

- **Travelpayouts / Aviasales Data API**: a cache of prices users found recently (not live).
  The limit is 600 req/min on v3 endpoints. Route discovery also reads the public data files
  (`data/routes.json`, `data/airports.json`, `data/pt/cities.json`) and `v1/city-directions`.
  Each item's link carries `search_date`, the day a
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

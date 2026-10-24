# Escapadinha

Travel-deals automation for the Portuguese market (placeholder brand). It collects round-trip
flight prices for every direct route from Lisbon, Porto, Faro, Madeira, Ponta Delgada and
Terceira (discovered automatically) plus ~20 long-haul destinations, keeps a price history, lists low prices on the website and flags promotions well below each
route's own historical median, and renders Instagram carousel slides (1080×1350 PNG) with
pt-PT captions into `./output/<date>/` **for manual review.** Approved promotions go into a
posting queue (Instagram daily slots, Telegram at once, D32). Instagram posts go out through the
Graph API as a carousel plus a story once its secrets are set (D36); until then due Instagram
posts wait (they keep their slot). Telegram posts go out through the Bot API as a photo message
in the public channel once its secrets are set (D38); until then they wait too.

**Integrity rule:** every price shown comes from a stored API observation (`price_observations`)
with its source, first `fetched_at` timestamp and the day a traveller found it (`found_date`).
The verbatim API responses of each run are archived as one gzip JSON object (`fetch_runs.archive_key`).
Nothing is estimated or invented. Each rendered deal carries a `meta.json` pointing back to that
row, its first run and the archive object: price → deal → observation → run → raw payload.

## Pipeline

```
Travelpayouts catalogues ──routes discover──▶ routes table (monthly; dormant after 30 days without prices)
Eurostat avia_par_pt ─────┘ (passengers per route-month: page order, far-month pass, thin-route notes, D45)
                                                   │ active routes
Travelpayouts API ──collect──▶ SQLite (price_observations, one row per offer)  (market=pt, every 30 min; months 4–6 once a day, D42)
                       └──────▶ data/objects/archive/runs/<run>.json.gz (raw responses)
                                   │
                               recheck  open deals: same trip still ≤ price, fresh, direct?
                                   │            no → status expired + EXPIRADO.txt
                                detect  two tiers vs the month's typical low (D24, D44):
                                   │      low price  ≥15% below          → route pages (no review)
                                   │      candidate  ≥30% and ≥15 € below, and a new low → a deal for review
                                   │    then the queue again (D40): still a candidate today?
                                   │            no → status expired + EXPIRADO.txt
                                enrich  GraphQL API, same cache (D43): checked bag? which agency?
                                   │      matched by the link's t= token; no match → unknown, no line
                                   ▼
                              deals (status: new)
                                   │
                         render deals ──▶ output/<date>/deal-LIS-LON-12/
                                            slide_01..03.png · caption.txt · meta.json
```

| Module | Role |
|---|---|
| `collector/` | `TravelpayoutsSource` (v3 `prices_for_dates`, rate-limited; asked with the route's rules, `direct=true` on nonstop-only routes), `plan.py` (pure: which route-months a run asks for, the day's pass, D42, narrowed to the busiest routes by demand, D45), `runner.collect` (runs a plan), `catalogue.py` (discovery downloads), `eurostat.py` (the demand dataset, D45), `graphql.py` (GraphQL `prices_round_trip` client + pure offer match, enrichment only, D43) |
| `discovery.py` | Pure: catalogues + supplements → direct routes with kind and pt-PT name |
| `demand.py` | Pure: Eurostat `avia_par_pt` JSON-stat → passengers per route-month (ICAO → IATA → city), the last twelve months and their mean, `rank_routes` (D45); `collector/eurostat.py` fetches and archives it |
| `routes.py` | Routes as data: `sync` (config → `routes` table), `apply_discovery`, `mark_dormant`, `active_routes`, effective rules per route |
| `storage/` | `schema.sql` + plain-SQL repository functions in `db.py`; `objects.py`/`s3.py` (object store: local dir or R2); `sync.py` (database pull/push, run lock, daily backups); `mirror.py` (photos and rendered slides in the store) |
| `run_path.py` | Fast or full path for a run: fingerprint of what the site shows, stored after each full path (D25) |
| `detector.py` | Pure functions: `baseline`, `confidence`, `evaluate` (threshold, euro floor, new low, D44), `low_prices`, `detect_route`, `detect` (both tiers) |
| `backtest.py` | The detector backtest (D44): replay of the stored runs on a read-only copy with several rule sets; `scripts/backtest_detector.py` runs it |
| `photos.py` | Pixabay search + download, credit stored in `photos` |
| `renderer/` | Jinja HTML/CSS → Playwright Chromium → PNG; `tokens.py` = design-system tokens |
| `captions/` | pt-PT caption templates (price, dates, timestamp, disclosure) and the WhatsApp text |
| `posting.py` | Posting queue rules (D32): pure daily-slot allocation, re-verification verdict, the publisher protocol (dry run) |
| `instagram.py` | Instagram publisher (D36): Graph API carousel + story, error mapping, token refresh |
| `pipeline.py` | Wires the DB to each step; `cli.py` exposes them |
| `site_data.py` | Website data contract v1: JSON export for the Astro site + fixtures (`contract/site/v1/`) |
| `website/` | `astro.py` (`site build`: npm, astro build, images), `routing.py` (`_redirects`/`_headers`), `deploy.py` (wrangler), `crawl.py` (`site crawl`) |

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
| `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_ACCOUNT_ID` | Optional. The Meta app's long-lived token (Instagram Login) and the professional account's id: [docs/runbooks/instagram.md](docs/runbooks/instagram.md). Both set = Instagram posts go out for real (see [Instagram](#instagram-decisions-d36)); either missing = due Instagram posts wait ("À espera do token") |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL` | Optional. The bot's token from @BotFather and the public channel's @handle (the bot is an admin allowed to post): [docs/runbooks/telegram.md](docs/runbooks/telegram.md). Both set = Telegram messages go out for real (see [Telegram](#telegram-decisions-d38)); either missing = due Telegram posts wait ("À espera do bot") |

In the Travelpayouts dashboard, join the **Aviasales** program and check under its
traffic rules that **Instagram/social media** traffic is allowed before posting.

## Running each step

```bash
uv run escapadinha routes discover         # find direct routes from the 6 airports (+ photos for new destinations, + Eurostat demand per route, D45)
uv run escapadinha routes discover --dry-run --no-photos   # show what would change, store nothing
uv run escapadinha routes list             # every route + active/dormant counts per origin (pt-PT)
uv run escapadinha collect                 # routes with prices × 3 departure months; the day's first run from 06:00 Lisbon: every active route × 6 (D42)
uv run escapadinha recheck                 # re-verifies open deals against the latest run
uv run escapadinha detect                  # latest run: low prices + promotion candidates per route; expires queued deals that aren't candidates today (D40)
uv run escapadinha enrich                  # latest run: baggage, selling agency and exact found time for its low prices and candidates (GraphQL, D43)
uv run escapadinha stats LIS-LON           # history size, min/max, current median
uv run escapadinha photos fetch            # one Pixabay photo per destination (cached)
uv run escapadinha photos fetch --dest LON --force --pick 2   # swap a photo you don't like
uv run escapadinha render deals            # renders deals with status 'new' → 'rendered'
uv run escapadinha render deals --deal-id 12
uv run escapadinha render guide voos-baratos-dicas
uv run escapadinha export site-data        # website data contract v1 (JSON) → web/src/data
uv run escapadinha run                     # review events → (monthly discovery) → collect → recheck → detect → enrich → publish due posts, then render → export → site build (Astro) → deploy only if something changed → review snapshot
uv run escapadinha queue list              # upcoming posts (Instagram slots, Telegram), Lisbon time; --all adds published/cancelled; Instagram token and Telegram channel notices
uv run escapadinha queue retry 12 telegram  # a Telegram send whose answer was lost, not in the channel: back in the queue (D38)
uv run escapadinha instagram token         # PC only: the Instagram token the pipeline renewed, to copy into the secret (D36)
uv run escapadinha run --full              # the same, always with render → export → site build → deploy
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
again reactivates it; the following collection that asks for it is its probe (for a route that
never had a price, the next daily pass: a run that didn't ask for a route never puts it to
sleep): with prices it stays, without it goes back to sleep. Nothing is deleted. Excluded routes
are left alone.

**Demand (DECISIONS D45):** the same discovery fetches Eurostat's `avia_par_pt` (passengers
carried per month on each airport pair with a Portuguese airport; public API, no key; reuse
authorised with the source acknowledged, which the site's "Como funciona" page does) and gives
every stored route `demand_pax_month` (the mean of the dataset's last twelve months, a month
without a value counting 0), `demand_period` (the last of those months) and the months themselves
(`route_demand`). Partner airports are summed into our city codes (Orly + Charles de Gaulle +
Beauvais = PAR) through the provider's `airports.json`; Eurostat labels pairs by ICAO, so
`demand.ICAO_IATA` maps the codes (a partner not in it adds nothing). The dataset lags about two
years (on 2026-10-19 the latest month was 2024-12), so the request asks for `demand.since_months`
(36) of history. Routes Eurostat has no pair for (small routes are not disseminated) keep NULLs and
behave as before. The answer is archived as it came under `archive/eurostat/`; a failed fetch is
reported with the discovery's other errors and the previous figures stay. `routes discover` prints
the summary: `Procura (Eurostat avia_par_pt, dados até 2024-12): 210 de 360 rotas com passageiros
por mês, 8 sazonais; mais procuradas: LIS-LON 200 779, …`. What the figure drives: the order of
origin pages and destination hubs (price, then demand), ties in the explorer, which routes the
day's pass asks the far months (below) and the route page's notes ("Rota com pouca procura: os
preços aparecem raramente" when a route has no recent price and fewer than
`demand.thin_pax_month` (5000) passengers a month; "Rota sazonal" when months had none). A
passenger count is never a price: it has no "€" and no `data-obs`.

**Photos:** every destination of an active route gets a Pixabay photo automatically (query:
`photos.queries` override, else the English city name), at most `photos.max_per_run` (40) per
discovery or run, so ~160 destinations take four runs. Failures are retried next time.

### What a run collects: the day's pass (DECISIONS D42)
Every run asks the routes that have returned a price for the next 3 departure months
(`collector.months_ahead`). Once a Lisbon day, the first run at or after 06:00 Lisbon
(`collector.daily_pass_hour`; the very first run too, when no pass was ever recorded) is **the
day's pass**: it asks every active route for 6 months (`collector.daily_months_ahead`):
- **months 4–6** build typical lows months before departure (Christmas, Carnaval, Easter), so a
  month enters the 3-month window with 30–45 days of history instead of ~7. The cache keeps a
  found day for about 7 days, so once a day misses little. Since D45 only the
  `collector.deep_routes` (80) busiest routes by Eurostat demand get them (`demand.rank_routes`;
  the rest of the pass asks `months_ahead` like a regular run, and an open promotion's far month
  is still asked); with no demand data stored, every route gets them as before;
- **routes that never returned a price** (no `last_observed_at`; 121 of 360 on 2026-10-15) are
  asked only by the pass, until their first price; then every run asks them.

The far month of an open promotion is asked on every run, so its recheck never waits for the pass.
The site shows each route-month's newest prices: for months 4–6, those of the latest pass (or
newer), so a run between two passes changes nothing on the site. The pass is kept in the `meta`
table (`collector.daily_pass`: Lisbon day and run id); a pass where every request failed doesn't
count, and the next run tries again. `collect` and the Actions summary say which pass ran:
`daily pass: months 1–6 of 360 routes · 2160 requests` (with demand data: `daily pass: months
1–6 of 80 routes, months 1–3 of 280 routes · 1320 requests`) or `regular pass: months 1–3 of 239
routes; 121 never-seen routes wait for the daily pass · 717 requests`. When the last recorded
pass started more than 30 h ago, `run` warns after the collection, in the log and the summary:
`Warning: the last daily pass (#57, 2026-10-15) started 30 h 05 min ago, more than 30 h: …`.

**Budget:** one request per asked route and departure month. On 2026-10-13 a run was 360
routes × 3 = 1080 requests in 5 min 40 s one at a time (≈190/min, latency-bound); with
`collector.workers: 8` in flight they take ~2 min, bound by the limit. The source allows 600/min;
`collector.requests_per_minute: 550` caps it client-side and a 429 still waits and retries.
Per day at 12 runs (D42): before the daily pass 360 × 3 × 12 = 12,960 requests; with it, one pass
of 360 × 6 = 2,160 and 11 runs of 239 × 3 = 717: 10,047. It saves requests from 4 runs a day up
(4,320 → 4,311 at 4, the fallback's cadence if the scheduler Worker is down, D41). Once the
never-seen routes are dormant the far months cost about 717 requests a day of their own.
Billed runner time is ~33 min/day (GitHub rounds each job up to the minute: the pass ~5, each
regular run ~2.2, plus review-triggered runs), ≈ 1000 min/month of the 2000 free ones (D41; see
*Minutes used* below).

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
`last_run_id` is that run or later (a live check counts as a sighting). The site reads each
route-month's newest prices: the latest run's, and for the months only the day's pass asks for,
the latest pass's or later (`pipeline.latest_offers`, D42).

Raw responses leave the database: each run (including live checks) writes
`archive/runs/<run id>.json.gz` through the `ObjectStore` interface (`storage/objects.py`:
get/put/list/delete/lock). Without R2 keys the store is `data/objects/`; with them, the R2 bucket.
Upgrading from schema v6 collapses duplicates (rows with a deal keep their id), parks the old
`raw_json` values and archives them per run on the next command (`reconstructed: true`), then
VACUUMs. On the real database: 9.4 MB → 0.65 MB plus 0.8 MB of archives.

### Baggage and agency from the GraphQL API (DECISIONS D43)
After detection, `enrich` (part of `run`, never fails it) asks the Aviasales GraphQL Flights Data
API (`POST /graphql/v1/query`, same token, same 7-day cache as the REST prices, 60 requests a
minute) about the run's promotion candidates and low prices: one `prices_round_trip` query per
(route, departure, return), candidates first, then low prices by discount, at most
`collector.enrich_per_run` (60) queries a run, skipping offers already matched. Each stored
offer is matched to the GraphQL row with the same `t=` token in its link (the same ticket from
the same search at the same agency price; the REST price is rounded to the euro and its airline
code can differ from `main_airline`, so the token is the reliable key; without a link the
fallback is the airline, the local dates and a value that rounds to the price). The match fills
`with_baggage`, `baggage_code` (`0PC` = no checked bag), `gate` (the selling agency) and
`found_at` (exact UTC time a traveller found it) on `price_observations` (schema v14). Rows
that disagree leave a field unknown; no row leaves all four null and nothing is printed: the
baggage line ("só bagagem de mão" / "com mala de porão incluída") appears in captions, the
WhatsApp text, the slides, promotion pages and low-price rows only when known, the agency only
on the review pages. Prices never change. Answers are archived like the REST ones, under their
own `enrich` run (`escapadinha enrich` prints "N GraphQL requests, M of K offers matched").
`paging.limit` is capped at 400 by the API; the cheapest rows come first.

## Configuration (`config.yaml`)

- `routes`: routes live in the database (`routes` table, `escapadinha routes list`); config
  only shapes them (DECISIONS D17):
  - `kinds`: default rules per kind. `europe` and `domestic` (the "Portugal" category): nonstop both ways,
    2–10 nights. `long_haul`: up to 1 stop each way, 7–21 nights. `direct_only` wins over
    `max_transfers` (stops per direction). Offers outside a route's rules are not collected
    (nights), are never deals and never count towards its typical low.
  - A route that takes only nonstop flights both ways (`direct_only`, or `max_transfers: 0`)
    asks the API for nonstop fares only (`direct=true`, DECISIONS D39). The cache keeps one
    offer per date pair, the cheapest, so a cheaper fare with a stop would otherwise hide the
    nonstop one (57 % of the rows on these routes were thrown away for a stop). Routes that
    allow a stop keep the plain call; the request count is the same.
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
- `collector`: `months_ahead` (3 = this month + 2, every run), `daily_months_ahead` (6, the
  day's pass) and `daily_pass_hour` (6, Lisbon: the day's first run from then is the pass; D42),
  `deep_routes` (80: how many routes, by demand rank, the pass asks the far months; D45),
  currency, `requests_per_minute` (550). Nights come from each route's rules. GraphQL enrichment (D43):
  `graphql_requests_per_minute` (55, the API allows 60) and `enrich_per_run` (60 queries a run, one per trip;
  0 turns it off).
- `demand` (D45): `since_months` (36: how much of Eurostat's monthly series to ask for; it lags
  about two years) and `thin_pax_month` (5000: below it a route without a recent price says
  "rota com pouca procura"; exported as `meta.demand.thin_pax_month`).
- `photos`: `queries` (Pixabay search per destination code) and `max_per_run` (40).
- `posting` (D32): `instagram_slots` (Lisbon time, default `09:00`, `13:00`, `19:00`),
  `max_per_day` (3 Instagram posts per Lisbon day), `max_check_age_hours` (6: a due post waits
  until a recheck or the approval verified the price this recently), `max_attempts` (5 publisher
  errors cancel a post) and `publishers` per channel (`instagram: instagram`, whose due posts
  wait while its secrets are unset; `telegram: telegram`, the same with its own; `dry-run` only
  logs, and settles the post).
- `instagram` (D36): `login` (`instagram`: Instagram API with Instagram Login on
  graph.instagram.com, the default; `facebook`: graph.facebook.com for an account linked to a
  Page, with a Page token that never expires: no refresh), `api_version` (`v23.0`),
  `refresh_days` (10: the token is renewed when fewer days remain), `images_wait_hours` (24:
  JPEGs still not on the site this long after the slot make each further wait a failed attempt).
- `telegram` (D38): `images_wait_hours` (24: the cover JPEG still not on the site this long
  after the approval makes each further wait a failed attempt).
- `origins_pt`: origin names in captions (LIS Lisboa … FNC Madeira, PDL Ponta Delgada, TER Terceira).
- `origins_article`: the article a name takes in a sentence (`OPO: o` → "desde o Porto", `FNC: a`,
  `TER: a`; unlisted origins take none), exported in `origins.json` for the site's titles.
- `detector`:
  - `threshold: 0.30` and `min_saving_eur: 15`: a promotion candidate needs
    `price ≤ typical_low × (1 − 0.30)` **and** `typical_low − price ≥ 15 €`.
  - `low_threshold: 0.15`: a low price needs `price ≤ typical_low × (1 − 0.15)` (must be ≤ `threshold`).
  - `lookback_days: 90` is how far back daily lows count.
  - A month's typical low is **mature** (D40) after enough daily lows, counting only days that
    saw `min_dates_per_day: 2` different departure dates (one-date days are three times as likely
    to be high outliers): `min_baseline_days: 7` for low prices and the site's typical lows,
    `min_baseline_days_promo: 10` spanning `min_baseline_span_days: 9` (first to last day) for
    promotion candidates (`min_baseline_days_promo ≥ min_baseline_days` is enforced).
  - `max_offer_age_days: 3` defines the freshness window. Prices travellers found in the last
    3 days are candidates, and older days form the baseline.
  - Confidence in a typical low (D44): `low` below the maturity gate, `high` with at least
    `confidence.high_days: 14` daily lows whose coefficient of variation is at most
    `confidence.high_max_cv: 0.25`, `medium` otherwise. `low_confidence: medium` is what low prices
    need (`high` is stricter). Posts claim "−x %" only at medium or high.
  - `require_new_low: true` and `new_low_margin: 0.05`: a candidate must also be 5 % below the
    cheapest offer seen for the route-month in the lookback window (every day, counted or not).
  - `baseline_min_lead_days: 7`: fares found less than a week before departure stay out of the
    typical low (they run dearer); they can still be candidates against it.
  - `dedupe_days: 7` stops the same trip being re-flagged unless it gets cheaper.
  - `max_deals_per_route: 1` caps deals per route per run (biggest discount first).
- `site.max_new_links_per_build: 300` (new low-price partner links per collection run, ≤ 900;
  the site data export creates them). Route pages list at most five low prices
  (`LOW_PRICES_PER_ROUTE` in `web/src/lib/routes.ts`).
- `site.data_dir: output/site-data/v1` (where `export site-data` writes; `web/src/data` once the
  Astro package exists), `site.max_low_prices_per_origin: 1500` (row cap per low-price file) and
  `site.expired_promotions_days: 30` (expired promotions stay in the export this long).
- `site.search_widget` (D34): the Aviasales search form's script `src` from Travelpayouts'
  widget constructor (https, a Travelpayouts widget host, the website's Project as `trs=` and,
  when `TRAVELPAYOUTS_MARKER` is set, our marker as `shmarker=`: validated); set since
  2026-10-15 (pt, EUR, aviasales.pt, website Project) by following
  [docs/runbooks/search-widget.md](docs/runbooks/search-widget.md). Test configs reset it to null
  (they use other Projects). `site.analytics_token: null`:
  Cloudflare Web Analytics runs in the zone's automatic setup, so no beacon token (it would count
  visits twice). Both go to the website contract's `meta.json` (null in fixtures).
- `affiliate.programmes` (D37): the affiliate blocks' programmes, `esim` (Yesim,
  `https://yesim.tech`), `activities` (Tiqets, `https://tiqets.com`) and `insurance` (`null`: none
  usable yet, EKTA closed). Each one `brand` + https `url` (the brand's own page, never a
  `marker=` link), optional `destinations` (city code → a deeper page). See "Affiliate links".
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
The collection, the live check and the review Function ask the same query
(`collector.travelpayouts.request_params` from the route's rules, D39), so on a direct-only
route a deal's nonstop fare no longer "disappears" when a cheaper fare with a stop shows up
for the same dates.

**Against today's typical low (D40).** After detection, every run also judges each deal still
waiting for review (`new`, `rendered`) again, with the detector's own rule, against its month's
current typical low and the route's current rules: a typical low mature for promotions, and the
deal's price 30 % and 15 € below it (a `price_cap` deal: under its cap while the typical low is
not mature). A deal that would not be detected now expires like the recheck's, with the reason:
`preço habitual ainda sem dados suficientes (5 de 10 dias)` or `já não é promoção face ao preço
habitual atual (101 €): 80 € fica 21% abaixo; são precisos 30% e 15 €`. Approved deals are left
to the price recheck (a human approved them on the figures the review showed). The 6 deals
waiting on 2026-10-16 were detected on 4–6-day typical lows; on the database of run 58 this rule
expires all of them (none of their months had 10 counted days; D40 has the replay).

### What counts as a deal: two tiers (DECISIONS D24)
Every price is measured against the route's **typical lowest price for the same departure
month**: the median of daily lows, where each day's low is the cheapest price travellers found
that day. Each run yields two outputs:

- **Low prices** (*preços baixos*): fresh offers at least `low_threshold` (15 %) below the typical
  low, one per trip dates. Not reviewed: the route pages list the latest run's low prices
  automatically, each with its found date and its own tracked link. They need a mature
  typical low (`min_baseline_days` daily lows); a `price_cap_eur` never makes a low price.
- **Promotion candidates**: fresh offers at least `threshold` (30 %) **and** `min_saving_eur`
  (15 €) below the typical low, at most `max_deals_per_route` per route per run, not the same
  trip again within `dedupe_days` unless cheaper, never an offer that already is a deal. They
  become deals in status `new` for review. The 15 € floor keeps small-fare routes out of the
  queue: on a 40 € route, 26 € is 35 % off but saves 14 €, so it is only a low price. They need
  a typical low mature for promotions: `min_baseline_days_promo` (10) daily lows spanning
  `min_baseline_span_days` (9) days.

**A mature typical low (D40).** A day's low counts only when that day saw `min_dates_per_day`
(2) different departure dates. With 4-day baselines 7 of the first 11 deals were not 30 % below
once more days were known (research `docs/research/2026-10-15-data-reliability.md`). On the
database of 2026-10-15 (runs 19–57) the old rules gave 8 candidates and 32 low prices on 10
routes; these give none of either until the busiest route-months reach 10 counted days (from
about 20–25 October). The reviewer sees each deal's baseline: "−39% vs. mínimo habitual 99 €
(10 dias em 12, de 54 € a 110 €)", i.e. 10 daily lows over a 12-day window, the cheapest and
dearest of them (each traced to its observation).

**Confidence, new low and lead time (D44).** On a mature route a −30 % day is a one-in-ten day
(the daily lows spread with a CV of about 0,20), so a candidate must also be a **new low**: at
least `new_low_margin` (5 %) below the cheapest offer seen for the route-month in the lookback
window. Each typical low gets a **confidence**: `low` below the maturity gate, `high` with
`confidence.high_days` (14) daily lows spread by at most `confidence.high_max_cv` (0,25),
`medium` in between; low prices need `low_confidence` (`medium`). The typical low takes only
offers found at least `baseline_min_lead_days` (7) before departure. A deal stores its confidence
and new-low flag at detection; the review pages show "· confiança média · novo mínimo", and a
post says "−x % face ao habitual" only at medium or high confidence (else, for a new low, "o
preço mais baixo que vimos nesta rota"). The values were measured with the backtest below and
are Miguel's to set (`docs/research/2026-10-18-detector-backtest.md` §5).

`detect` prints both per route (column "Lows" and the deals created; "Baseline" ends with the
confidence).

**Backtest (D44).** Any change to these rules is measured first:

```bash
uv run escapadinha store pull
uv run python scripts/backtest_detector.py data/escapadinha.db --preset d44 --days 14 --candidates --state
uv run python scripts/backtest_detector.py data/escapadinha.db --preset data-reliability --runs 19-57
```

Read-only: the database file is opened read-only and copied into memory. The script replays every
completed collection run of the window with one rule set per column, judges each candidate with
the pipeline's own recheck over the next 24 h and against today's typical low, counts low prices
and new lows per route kind, and (`--state`) lists every route-month's typical low with and
without the lead-time filter. `--json out.json` writes the same figures as data. The first preset
reproduces the replay table of `docs/research/2026-10-15-data-reliability.md`.

Comparing against all fares would be wrong. A route's cheapest dates are always far below the
median of all fares, so that rule flags almost every route on every run. On the first real data
it flagged 9 of 10 routes.

The source cache records when each price was found and covers about a week, so baselines
exist from the **first run**. Until a month's typical low is mature for promotions, `detect`
reports **warming up** (column "Baseline": days counted / `min_baseline_days_promo`, and the
span) and flags no promotion. The one exception is a route with an explicit
`price_cap_eur` (`rule = price_cap`); the caption then makes no "% below" claim.

Every deal names its arrival airport. Remote airports (for example Paris-**Beauvais**,
Milan-**Bérgamo**) also appear in the headline: "Porto → Paris (Beauvais)".

## Approval queue

```bash
uv run escapadinha review            # opens http://127.0.0.1:8765 (local only; Ctrl+C to stop)
```

The page (in Portuguese) has four tabs: **Por rever**, **Aprovados**, **Publicados** and **Fechados**
(expired or rejected). Each deal shows its three slides, the caption with a copy button, the
affiliate link, and the facts behind it: price, typical low (with its days, their window and the
cheapest and dearest daily low, D40), discount, arrival airport, found/checked dates and the last
recheck.

- **Verificar preço agora** fetches that route and month from the API now and rechecks the deal
  (without R2 keys: stored as a `live_check` run, a moved price expires the deal; with R2 keys
  it only reports, and the next run's recheck expires it).
- **Aprovar** checks the price live first. If it moved, the approval is refused with the reason
  and nothing is written: the next collection's recheck expires the deal. A deal without an
  affiliate link can't be approved.
- **Rejeitar** (optional note) and **Marcar como publicado** (optional post URL) record the decision.
  With the Instagram secrets set, the pipeline posts approved promotions itself and writes this
  decision for you ([Instagram](#instagram-decisions-d36)); mark by hand only what you posted
  yourself.
- Approved deals show the **WhatsApp text** with a copy button (also on the phone page).
- Approved deals keep being rechecked every 30 min. If the price moves before you post, the deal
  expires and the page tells you.

The CLI applies the same rules:

```bash
uv run escapadinha deal check 12          # the price now, then each channel's post (when, or its link)
uv run escapadinha deal approve 12 --note "bom deal"
uv run escapadinha deal reject 12 --note "datas fracas"
uv run escapadinha deal published 12 --url https://www.instagram.com/p/...
```

Status flow: `new → rendered → approved → published`. `rejected` and `expired` are final;
`expired` is only set by price checks.

### Automatic approval for the website (DECISIONS D46)

Since 2026-10-24 the pipeline approves the best candidates itself, so they reach the site
without waiting for a tap. In the full path, right after rendering, `escapadinha auto-approve`
(the run does it) takes every `rendered` candidate that passes the rules in `review.auto_approve`
(`config.yaml`): rule `median`, confidence `high` in the typical low (D44), a new low, nonstop both
ways, a known found time at most 48 h old, and at most 3 automatic approvals a Lisbon day. It then
approves it exactly as you would: the **live price check is the gate** (a moved price writes
nothing; the next recheck expires the deal), the approval is an ordinary review event (actor
`auto:regras`, note *aprovação automática (D46)*), applied in the same run, so the deploy that
follows publishes the promotion page. Both review pages list it under **Aprovados** with that
note; **Rejeitar** there takes it down (the page expires, as always). Everything else waits for
you under **Por rever** with the reason it was left (*confiança média (precisa de alta)*, *não é um
novo mínimo*, …) in the run log. `max_per_day: 0` only reports; `enabled: false` turns it off.

### Review decisions are events (D26)

Approve, reject and published never change the database directly. The page, the CLI and the
review Function on Cloudflare (on the phone, below) each write one **review event** to the object store
(`review/events/pending/<time>-<id>.json`, shape in `contract/review/v1/event.schema.json`), and
the pipeline applies them:

- **Without R2 keys** the database is on this PC, so the decision is applied right away (same
  output as before) and the event goes to `review/events/archive/<YYYY-MM>/` under `data/objects/`.
- **With R2 keys** the event goes to the bucket and the next `escapadinha run` applies it (first
  step of every run). The CLI and the page say *pendente* and list the pending decisions; a deal
  with a pending decision accepts no other one until it's applied. They decide on your local
  copy, so they refuse while the bucket has a newer database ("corre `escapadinha store pull`
  primeiro") and say so when the deal isn't in your copy ("O deal N não existe nesta base de
  dados.").
- When applied, each event is checked again against the deal's status at that moment. One that no
  longer fits (the deal expired meanwhile, was already decided, doesn't exist, the file is broken)
  is archived as *recusada* with the reason and the run carries on. Applying the same event twice
  does nothing.
- An **approval expires after 24 hours** (`review.approve_max_age_hours` in `config.yaml`): if its
  live price check is older than that when a run applies it, it's refused ("Aprovação com mais de
  24 h: verifica o preço outra vez.") and you approve again, with a fresh check. Reject and
  published have no age limit.

At the end of every run the pipeline writes **`review/snapshot.json`** (`contract/review/v1/
snapshot.schema.json`): the queue, approved deals, the latest published and closed ones, each with
price, dates, discount, caption, slide links, the live-check query and last recheck, plus the
pending decisions, the latest outcomes and the review rules (`review_rules.approve_max_age_hours`,
so a review UI can warn before an approval gets too old). Slides of deals still under review are copied to
`review/slides/<id>/` as WebP (they aren't on the public site yet).

### Posting queue (DECISIONS D32)

> **Paused since 2026-10-24 (D46).** Miguel's decision: nothing goes out on Instagram or Telegram
> until he says so; only the website publishes. `posting.publishers` is `paused` for both channels:
> approvals still queue their posts, every due post waits (*Em pausa por decisão do Miguel…* in
> `queue list`), nothing is settled. To resume, switch the names back to `instagram` / `telegram`
> after looking at `queue list`: the backlog would go out for every promotion still valid.

When a run applies an approval it queues the promotion twice: **Instagram** at the next free daily
slot (09:00, 13:00, 19:00 Lisbon time, at most 3 a day; `posting` in `config.yaml`) and
**Telegram** at once. Every run, after detection and before the fast/full path decision (so after
its recheck, and on the fast path too), publishes the posts that are due:

- a promotion that **expired** or was **rejected** cancels its queued posts, due or not, with the
  reason (*cancelada: A promoção expirou: o preço subiu para 80 €.*); one you marked published by
  hand cancels its Instagram post (Telegram still goes if its price was verified in the last 6 h;
  published promotions aren't rechecked, so after that it is cancelled rather than waiting);
- a due post goes out only if the price was verified (the run's recheck, else the live check you
  ran before approving: its time, not the approval's) in the last 6 h; otherwise it waits for a
  run that verifies it;
- at most one Instagram post per run, so a backlog never goes out in a burst;
- a publisher error keeps the post queued and retries next run; after 5 errors it is cancelled.

Publishers plug in through `posting.publishers`. A channel on the **dry-run publisher** only
logs what would be posted (`[dry-run] Telegram · deal 12 · Lisboa → Londres · 58 € · agendada
para ...` and the full text) and settles the post. Instagram (`instagram: instagram`) and
Telegram (`telegram: telegram`) without their secrets are not a dry run: their due posts **wait**
("À espera do token: …", "À espera do bot: …", no attempt counted), so no promotion loses its
post before the secrets are set; an expiry or a rejection still cancels them as usual.

```bash
uv run escapadinha queue list         # 2 publicações agendadas: Instagram deal 12 ... 01/12/2026 às 09:00 · agendada
uv run escapadinha queue list --all   # also published and cancelled posts: publisher, post link, story, reason
```

### Instagram (DECISIONS D36)

With `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_ACCOUNT_ID` set (`.env` and Actions secrets; setup
in [docs/runbooks/instagram.md](docs/runbooks/instagram.md)), a due Instagram post goes out
through the Graph API (Instagram API with Instagram Login, `graph.instagram.com`):

1. the promotion's JPEG slides on the site (`https://pontonomada.pt/img/promos/<id>/slide_NN.jpg`,
   written by `site build` next to the WebP ones) must answer 200 to a HEAD (redirects followed,
   https only); right after an approval the slot can come before the full path deployed them,
   and the post *waits* (no attempt counted) for up to `instagram.images_wait_hours` (24) after
   its slot; after that each run counts a failed attempt, so 5 of them cancel it with the reason;
2. the API's publishing limit (`content_publishing_limit`) must leave room for the carousel and
   its story, else it waits;
3. a **carousel**: one container per slide, each polled until Meta has processed it, then the
   carousel with the caption, polled the same way (about a minute at most; longer: the next run
   continues with the same carousel container), published, its permalink fetched;
4. a `published` decision with that permalink (`pipeline.mark_published`, actor
   `instagram-publisher`; review event v1 takes any actor text): applied at once without R2 keys,
   by the next run with them; the promotion's page then links the post (**Ver no Instagram**);
5. a **story** with the cover slide. If it fails, the carousel stays published and only the
   story is retried, for up to 6 h after the carousel (then *não sai*).

Nothing is ever posted twice: every container and media id is stored on the queue row as soon as
Meta returns it, the caption is stored at the first attempt and reused by every retry, and
before creating a carousel the publisher looks for one with that caption among the account's
latest posts (a run that died right after publishing). Graph errors: an invalid or expired token
(code 190, on any call, also with Facebook Login), rate or publishing limits and missing
permissions **wait**; media Meta refuses for good **cancels** the post with the reason; anything
else is a failure, retried up to `posting.max_attempts` (5).

**The token** lasts 60 days. When fewer than `instagram.refresh_days` (10) remain (or, for a new
token whose expiry is unknown, once it is a day old), the run renews it. GitHub secrets can't be
written from a run, so the new token is kept in the object store (`private/instagram/token.json`,
never in the database or a log) and later runs use it; the run log and `queue list` say
*"Token do Instagram renovado a …: atualiza o secret INSTAGRAM_ACCESS_TOKEN"*. To update it:
`uv run escapadinha instagram token` on the PC (refused on CI) prints it; paste it into the
`INSTAGRAM_ACCESS_TOKEN` secret (GitHub → Settings → Secrets and variables → Actions) and `.env`.
An expired or refused token posts nothing: due posts wait and the run log and `queue list` say
why, until Meta accepts a token again. With `login: facebook` nothing is refreshed: use a Page
token that never expires (runbook).

### Telegram (DECISIONS D38)

With `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL` (the public channel's @handle, e.g.
`@pontonomada`, or its numeric id: anything else pauses Telegram, with a notice) set (`.env` and
Actions secrets; setup in [docs/runbooks/telegram.md](docs/runbooks/telegram.md)), a promotion's
Telegram post goes out on the first run after its approval through the Bot API (`sendPhoto`):

1. the photo is the cover slide's JPEG on the site (`…/img/promos/<id>/slide_01.jpg`), which
   Telegram fetches by URL; it must answer 200 to a HEAD first, else the post *waits* for the
   deploy (no attempt counted) for up to `telegram.images_wait_hours` (24) after the approval,
   then each run counts a failed attempt. In practice the approval's own run deploys it and the
   message goes out on the next run;
2. the caption is the WhatsApp text (stored partner link and the disclosure), plain text, never
   cut: over Telegram's 1024 characters the post is cancelled with the reason;
3. the message id and link (`https://t.me/<handle>/<id>`) are stored on the queue row.
   `queue list` shows the link next to the promotion's posts still to go, `queue list --all` on
   the row itself, and `deal check <id>` lists each channel's post with its link. The promotion
   is not marked published: Instagram is its main channel.

Nothing is sent twice: a record of each send goes to the object store
(`posting/telegram/deal-<id>.json`) before the request and gets the message id after it. A send
Telegram refused, or that never reached it (no connection), is retried; one whose answer was lost
(a timeout after the request went out, an unreadable answer, a run killed before saving it) is
**cancelled** with *"… pode ter saído. Confirma no canal …"*: Telegram can't tell a bot what is
in its channel, so a lost answer is never resent by itself. `queue list` lists it (*Envio ao
Telegram por confirmar: deal 12 …*) until you check the channel; if it isn't there:

```bash
uv run escapadinha queue retry 12 telegram   # back in the queue (with R2: from the next run), sent once
```

(refused, with the reason, when the message did go out or there is no such send). A message sent
by a run whose database never reached R2 is adopted from the record on the next run. Errors: 429
(rate limit), 401 (the token) and a refused channel (any 403, or a 400 such as *chat not found*,
*need administrator rights*, `CHAT_WRITE_FORBIDDEN`) **wait**, no attempt counted, with a notice
in `queue list` until a message goes out again: a setup mistake loses no post. A message refused
for good (photo dimensions or format, caption too long) is **cancelled** with the reason; a photo
Telegram couldn't fetch right now, 5xx and the rest are failures, retried up to
`posting.max_attempts` (5). The token is part of the API URL: it never appears in an error, a log
or the database.

Every approved promotion also gets a short **WhatsApp text** (pt-PT: destination and arrival
airport, price, dates, when the price was found and when we checked it, the affiliate link and the
disclosure), in the review snapshot (`whatsapp_text`) and on both review pages with a copy button.

### Review on the phone: https://pontonomada.pt/review (DECISIONS D29)

The same queue, in Portuguese, served by a Cloudflare Pages Function from `review/snapshot.json`.
Open **https://pontonomada.pt/review**, sign in with the e-mail code from Cloudflare Access (only
Miguel's e-mail is allowed), and for each candidate you see the slides (swipe), price, dates,
airline, the baggage line and the selling agency when the GraphQL match found them (D43),
discount, found and verified times (Lisbon time), the affiliate link, the caption and
the WhatsApp text (when the snapshot has it) with copy buttons.

- **Verificar preço** asks Travelpayouts now, with the same query and rule as the pipeline
  (`pipeline.price_now`); it stores nothing.
- **Aprovar** runs that check first: a moved price refuses the approval with the reason and writes
  nothing. **Rejeitar** (optional note) and **Marcar como publicado** (optional post link) need
  no check.
- Each decision is one event in `review/events/pending/` (actor = your Access e-mail), then one
  `repository_dispatch` (`review-decision`) starts the pipeline, which applies it within minutes.
  If GitHub can't be reached the page says *a decisão ficou guardada; aplica-se no próximo run*:
  the event is kept and the next scheduled run (≤ 30 min) applies it.
- The page shows when the snapshot was made (and warns when it's over 3 h old), pending decisions
  (a deal with one accepts no other) and recent refusals with their reason. An approval applied
  more than 24 h after its check is refused, as everywhere (D26).

Setup (done once by Miguel, in the dashboards): an Access application on `pontonomada.pt/review`;
on the Pages project (Production) the variables `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, the secrets
`GITHUB_DISPATCH_TOKEN` (fine-grained PAT, this repo, *Contents: read and write*) and
`TRAVELPAYOUTS_TOKEN`, and the R2 binding `STORE` to the pipeline's bucket. The Function checks the
Access token itself (signature, audience, issuer, expiry), because `ondestaanocas.pages.dev` is not
behind Access. The step-by-step test from the phone (pt-PT) is
[`docs/runbooks/review-phone.md`](docs/runbooks/review-phone.md).

The code is in `web/functions/` (TypeScript, no npm dependencies) and is tested with the web
package (`cd web && npm test`). It ships with every `site deploy`: wrangler runs in `web/` and
compiles `web/functions/` (relative imports only, no npm package: a package import stops the
deploy), and the deploy hash (and the run's code fingerprint) include those files, so a
Function change redeploys.

## Public website

The website is the Astro package in [`web/`](web/) (see "The Astro package" below), built from
the website data contract (JSON) that the pipeline exports. It's the Instagram "link na bio". The
brand is **Ponto Nómada** (Instagram still `@ondestaanocas` until renamed); it's **live at
https://pontonomada.pt** on Cloudflare Pages (project `ondestaanocas`; the old
`ondestaanocas.pages.dev` and `www` hosts 301 there, D19). It replaced the first site, built with
Jinja from the database, on 2026-10-14 (the cutover, #23, D35).

```bash
uv run escapadinha export site-data   # the contract JSON → web/src/data (site.data_dir)
uv run escapadinha site build         # npm ci if needed, astro build → web/dist, images, _redirects, _headers
uv run escapadinha site preview       # http://127.0.0.1:8766 (web/dist; _redirects not applied)
uv run escapadinha site setup         # one-time: create the Cloudflare Pages project (REST API)
uv run escapadinha site deploy        # upload web/dist + the review Function if they changed (--force to always)
uv run escapadinha site crawl --sitemap https://pontonomada.pt/sitemap.xml   # every URL: 200 or a 301 to a 200
```

| Pages | |
|---|---|
| `/` | Live promotions, then recently expired ones, latest itineraries and tips |
| `/promos/<id>-<origem>-<destino>/` | A promotion: slides, details, booking button (live only), expiry notice (expired: `noindex`) |
| `/voos/<origem>-<destino>/` | A route: promotions, recent low prices, calendar, typical low per month (D30) |
| `/partidas/<origem>/`, `/destinos/<destino>/` | Origin pages and destination hubs (+ index pages) |
| `/explorar/`, `/pontes/<feriado>-<ano>/<origem>/` | Explorer and long weekends (D31) |
| `/roteiros/<slug>/`, `/dicas/<slug>/` | Reviewed itineraries and tips (D33) |
| `/sobre/`, `/privacidade/`, `404.html`, `sitemap.xml`, `robots.txt` | (D34) |
| `/review` | The review queue (Pages Function behind Access, D29) |
| `_redirects`, `_headers` | Cloudflare Pages rules (not pages), see "Domain and redirects" |

- **Only approved deals go public** (by you, or by the rules of D46); an expired one keeps its page for
  `site.expired_promotions_days` (30) after it expired, `noindex` and without a booking button;
  after that its links 301 to its route page. Deals that expired or were rejected before approval
  never appear.
- **Traceable prices:** every element showing a price carries `data-obs`, `data-deal` or
  `data-route` (`web/test/traceability.test.ts`, D2).
- **Images:** `site build` converts each promotion's rendered slides into
  `web/dist/img/promos/<id>/` (`slide_NN.webp` 1080 px, `thumb.webp` 540 px, `og.jpg`), the paths
  `promotions.json` names; on a CI runner the slides come from the object store (each once).
  Each slide is also written as `slide_NN.jpg` (not in the contract, no page shows it): the
  Instagram publisher hands those public URLs to Meta, whose API takes JPEG only (D36).
- **`site build`** (`website/astro.py`) runs `npm ci` only when `web/node_modules` is missing or
  was installed from another `package-lock.json` or by another Node version, platform or
  architecture (a stamp in node_modules), then `npm run build` with `SITE_DATA_DIR`
  = the export, and refuses to go on without an export. It prints pages per type, images,
  redirects and the size (real data, 2026-10-14: 627 pages, 31 MB, ~8 s, ~18 s with `npm ci`).
  Node 22+ is required (on Windows `npm.cmd` is found on the PATH or in `C:\Program Files\nodejs`,
  `website/node.py`). On `run`'s full path npm ci, the build and the deploy share one 20-minute
  budget (`node.FULL_PATH_SECONDS`): a command that hangs fails the run with the end of its
  output, leaving time to push the database inside the job (D35).
- **`site deploy`** uploads `web/dist` with `npx wrangler@<site.wrangler_version>` running in
  `web/`, so the review Function (`web/functions/`) ships in the same deployment. It refuses a
  fixture build (`<html data-fixture="true">`) and skips the upload when the content hash (the
  build plus the Function's sources, ignoring the build's own timestamps) is the last deploy's
  (kept in the database, `meta` `site.deployed`).
- **Run integration:** `escapadinha run` exports, builds and deploys on its full path only
  (something the site shows changed, see [GitHub Actions](#github-actions-decisions-d25)), and
  deploys only when `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are set.
- **Old URLs:** `site crawl --sitemap <url or file>` checks every URL of a sitemap on the live
  site (no redirect followed: 200, or a 301 whose target answers 200; anything else is listed
  and the command exits 1). `--base https://<hash>.ondestaanocas.pages.dev` crawls a preview
  deployment instead, `--dist web/dist` a local build with its `_redirects`. The old Jinja site's
  sitemap, saved before the switch, is `docs/cutover/jinja-sitemap-2026-10-14.xml` (363 URLs):
  crawled clean on the live site every day of the cutover week (2026-10-14 to 2026-10-21), after
  which the Jinja code was deleted (#23 phase 2).

### Domain and redirects

- `site.base_url` is the one switch: canonical URLs, Open Graph, sitemap and robots.txt use it
  (through `meta.base_url` of the contract). `site.domain` names the final domain; `site build`
  reminds you while `base_url` isn't on it.
- **Old host → new domain** is a Cloudflare **Bulk Redirect** (account level, free, set up once
  by hand), because Pages `_redirects` can't match on the host (D19). It keeps path and query,
  so every old link opens the same page on the new domain.
- **`_headers`** (generated): `X-Robots-Tag: noindex` on `site.legacy_hosts` other than the
  `base_url` host, and on per-deployment `<hash>.<project>.pages.dev` URLs.
- **`_redirects`** (generated by `site build`, `website/routing.py`, 301): every older path of a
  page whose path changed (history in the database, `meta` key `site.paths`, by stable key:
  `deal:<id>`, `route:<key>`, `destination:<code>`, `origin:<code>`; an old
  `data/site_paths.json` is merged in), short `/promos/<id>` links, promotions no longer on the
  site → their route page, the old guides `/guias/<slug>/` → the tip or itinerary whose
  `legacy_path` names them (else `/dicas/`), and `site.redirects` from config. A rule never uses
  a path that is a page now (Pages applies redirects before files), never points at a path the
  build doesn't serve (left out before Cloudflare's 2000-rule limit counts) or at another rule
  (chains collapse to the final page); left-out rules are printed by `site build`. Within 10 % of
  the limit `site build` warns, above it the build fails instead of dropping old links. The paths
  a build implies are stored as `site.paths` only once it is live (after `site deploy`, or a
  deploy skipped as unchanged); a promotion that left the site is folded into its route's
  history (its old paths and `/promos/<id>` become old paths of the route page).

### Website data contract v1 (DECISIONS D27)

The Astro site (M3, `web/`, see below) is built from JSON files only. Their shape is a JSON Schema
(draft 2020-12) in [`contract/site/v1/`](contract/site/v1/); the Python export writes them and
the tests validate every export against the schemas.

```bash
uv run escapadinha export site-data                 # → site.data_dir (web/src/data)
uv run escapadinha export site-data --out DIR --no-new-links   # no partner-links API request
uv run escapadinha export fixtures --db data/escapadinha.db    # regenerate the committed fixtures
```

| File | Content |
|---|---|
| `meta.json` | Contract version, `generated_at`, latest run id, detector settings, list of files, counts, `fixture` flag |
| `labels.json` | pt-PT names from `i18n_pt.py` (airlines, airports + remote flag, route kinds, months, disclosures: `site`, `post` and, since D37, `affiliate` for the affiliate blocks) |
| `origins.json` | The Portuguese origins (name, slug, origin page path `/partidas/<slug>/`, active/dormant routes, low prices, live promotions) |
| `routes.json` | Every route: kind, status, rules, page path, typical low and plain average per departure month (null while the month has too few days), cheapest fresh offer, calendar (cheapest fresh offer per departure date, D30), counts |
| `destinations.json` | Destination hubs: city, hub path `/destinos/<slug>/` (stable once exported: a same-name city found later takes its code; paths remembered in `site.paths` for 301s), airports, routes from Portugal, photo credit |
| `promotions.json` | Approved deals, live and expired after approval (for `site.expired_promotions_days`, 30, after expiring): offer, typical low, paths, slide/thumb/OG image paths, tracked link (live only), expiry reason with the recheck price's observation |
| `low-prices/<ORIGIN>.json` | One origin's low prices for the explorer: compact rows `[obs, dest, price, dep, ret, found, fetched, airline, stops, airport, typical, link]` |
| `pontes.json` | Every long weekend ("pontes", D31) of `content/holidays.yaml`, past ones too: holiday, days off, bridge day, travel window, one page path per origin. No prices, no display text (added within v1: older exports lack it) |
| `affiliates.json` | Affiliate blocks (D37): each programme's brand (`esim`, `insurance`, `activities`; null while not configured) and one tracked link per (reviewed article, configured programme it lists). Added within v1: older exports lack it |

- **Raw values:** ISO dates, UTC timestamps, euros as numbers. pt-PT formatting is the site's job,
  with the names from `labels.json`. `found` (traveller) and `fetched` (us) are separate fields.
- **Traceable:** every price sits next to its observation id; typical lows and averages next to
  their route (recomputable); a promotion's typical low is its deal's stored baseline.
- **Links:** only from the partner links API (`pipeline.low_price_links` / `website_links`); the
  export creates missing ones (from the run's link budget, D24); the Astro build only reads them.
- **Size budget:** a low-price file holds at most `site.max_low_prices_per_origin` (1500) rows,
  biggest discounts kept, ~135 bytes per row (tested ≤ 160), one row per line, sorted and
  deterministic (stable diffs, gzip ~4× smaller).
- **Run integration:** the full path of `run` (D25) exports into `web/src/data` right before
  `site build` (the local disk, not R2; git-ignored).
- **Fixtures** (`contract/site/v1/fixtures/`, committed): ~10 routes from 3 origins of the real
  database, opened read-only and copied into memory. Booking links become
  `https://example.com/parceiro/<sub_id>`, photographers' names a placeholder. When no deal was
  approved yet, the copy marks the newest deal live and an expired one as approved before it
  expired, so both promotion states exist (`meta.fixture: true`: never deploy them).

### The Astro package `web/` (DECISIONS D28)

The M3 website is a separate npm package in [`web/`](web/) (Astro 7, static output, Tailwind 4
with the design-system tokens). It reads only the contract JSON, so it builds and tests without
Python. It is the live site since the cutover (#23, D35): home page, promotion pages (live and
expired), route pages, origin pages and destination hubs (D30), the explorer and the ponte pages
(D31), itineraries and tips (D33), SEO (D34). The pipeline builds it with `escapadinha site build`
(above); the npm commands below are for working on it.

```bash
cd web
npm ci                     # Node 22+ (CI uses 22)
npm run typecheck          # tsc, strict: functions/ without Node types, then src/lib + test
npm test                   # vitest: builds the site from the fixtures and checks the HTML
npm run build:fixtures     # → web/dist from contract/site/v1/fixtures (test data, never deployed)
npm run dev:fixtures       # http://localhost:4321 on the fixtures
npm run build              # → web/dist from SITE_DATA_DIR (default web/src/data, git-ignored):
                           #   needs exported data first, see below; fails without it on purpose
                           # (every build is `astro build --force`: Astro's content cache misses
                           #  front matter schema changes, D37)
npm run lhci               # Lighthouse CI on web/dist (mobile, ≥ 0.9 perf/a11y/SEO)
npm run tokens             # regenerate src/styles/tokens.css + src/lib/tokens.ts after docs/design/tokens.json changes
```

- **Which build:** on a fresh checkout (and in CI) the build to run is `npm run build:fixtures`;
  `npm test` builds the same way. Plain `npm run build` is the build from real data: it reads
  `web/src/data` (or `SITE_DATA_DIR`) and **fails on purpose** while that folder is empty, so a
  site is never built from nothing or silently from the fixtures. To fill it, export the data from
  the repository root: `uv run escapadinha export site-data` (writes `web/src/data`), then
  `cd web && npm run build`, or `uv run escapadinha site build` for the whole step.
- **Data:** `SITE_DATA_DIR` (relative to `web/`) names the contract directory; without it the
  build reads `web/src/data` and stops with a clear message when it is missing. Every file is
  validated against `contract/site/v1/*.schema.json` (ajv) before any page renders; a mismatch
  fails the build naming the file and the field. A fixture build carries `<html data-fixture>`.
- **Pages:** `/` (live promotions, then recently expired ones), `/promos/<id>-<origem>-<destino>/`
  (the path from the contract, same URLs as today), `/sobre/` ("Como funciona") and
  `/privacidade/` (linked from every footer), `404.html`, `robots.txt`, `sitemap.xml`,
  `og-default.png`. An expired promotion is `noindex`, has no booking button and says why (the
  recheck's reason).
- **SEO (D34):** every page has its canonical URL (contract `base_url` + path), OpenGraph and
  Twitter tags (`og:type` `article` on itineraries and tips). `sitemap.xml` is written after the
  build from the built pages themselves (`src/lib/sitemap.ts`): every page with a canonical URL
  and without `noindex`, so expired promotions, empty or past pontes, empty listings and drafts
  leave it by themselves (fixture build: 31 of 81 pages). `robots.txt` points at it. JSON-LD
  (`src/lib/structured-data.ts`): `WebSite` + `Organization` on the home page, `Trip` with an
  `Offer` on live promotions (the offer's own price, `data-obs`/`data-deal` on the block, never
  on an expired one), `Article` on itineraries and tips (`dateModified` = `last_checked`), and a
  `BreadcrumbList` with the visible trail (`Breadcrumbs.astro`) on promotion, route, origin,
  destination, itinerary and tip pages. Checked twice: `npm run typecheck` against the schema.org
  vocabulary (`schema-dts`), `web/test/seo.test.ts` with a JSON Schema per type (`test/jsonld.ts`).
- **Search widget and analytics (D34):** with `meta.search_widget` (config `site.search_widget`)
  route and destination pages get "Pesquisar outras datas": a "Pesquisar voos no Aviasales"
  button; the partner's script (`src/lib/search-widget.ts`) is added only when the visitor presses
  it (nothing from the partner loads before, as the privacy page says); never on the home page or
  promotions; nothing at all while unset (the fixture build). With `meta.analytics_token` every
  page gets Cloudflare's beacon script; null now (automatic setup at the edge). The site sets no
  cookies (a test fails on `document.cookie` in the build or the sources).
- **Route, origin and destination pages (D30):** `/voos/<origem>-<destino>/` (the contract's
  `path`, the Jinja site's URLs): promotions on the route, recent low prices (biggest 5 discounts,
  by date, each with its found-on date, our first sight and its own partner link, the disclosure
  under the list), a calendar of the cheapest found price per departure day, the typical low per
  month ("ainda sem dados suficientes" while a month has too few days), a notice on dormant
  routes, links to the origin page and the destination hub. `/partidas/<origem>/`: every
  destination from that airport by kind, with the cheapest price found now. `/destinos/<destino>/`:
  every Portuguese origin with a route there, its cheapest price and best months (lowest typical
  lows). Index pages `/partidas/` and `/destinos/` (nav "Destinos"). Hubs and route pages link the
  city's reviewed itinerary when there is one (`src/lib/itinerary.ts`, `ItineraryLink.astro`);
  hubs also list the reviewed tips whose `destinations` name the city (`src/lib/related.ts`).
- **Itineraries and tips (D33):** MDX files in `web/src/content/itineraries/` and
  `web/src/content/tips/`; the file name is the slug, the page is `/roteiros/<slug>/` or
  `/dicas/<slug>/`, listed on `/roteiros/` and `/dicas/` and (the latest three of each) on the home
  page. Front matter (schemas in `src/lib/content.ts`, checked on every build, drafts included):
  `title`, `description`, `last_checked` (the day every fact was checked), `sources` (`title` +
  https `url` of the official pages), `best_months` (1–12), `reviewed` (default `false`); an
  itinerary adds `destination` (the city code, one itinerary per city) and `days`, a tip `topic`
  and optional `destinations`; `legacy_path` keeps an old site path for the cutover's redirects.
  **Only `reviewed: true` entries are built**, and a reviewed entry needs `last_checked` and at
  least one source; drafts show only in the dev server (`npm run dev` / `dev:fixtures`), with a
  "Rascunho" notice and `noindex`. Each article ends with "Factos verificados a <data>" and its
  sources. **No prices in content:** the pt-PT lint refuses "€", "EUR" and amounts in euros; link
  the official source instead. Test-only entries (`fixture: true`) live in
  `web/test/fixtures/content/` and are built only from fixture data. A fixture build builds the
  real reviewed entries too; there a test-only itinerary wins over a real one for the same city,
  and only test-only articles get (placeholder) affiliate links, so approving real content never
  breaks the fixture build, the web tests or the committed fixtures. The old "guia rápido" is now
  the tip `web/src/content/tips/voos-baratos.mdx` (`/dicas/voos-baratos/`, approved 2026-10-15;
  `legacy_path: /guias/voos-baratos-dicas/`).
- **The #19 articles:** five itineraries (`barcelona-em-3-dias`, `paris-em-4-dias`,
  `roma-em-3-dias`, `madeira-em-3-dias`, `sao-miguel-em-3-dias`: the five destinations with low
  prices in the latest run) and five tips (`bagagem-de-mao`, `esim-ou-roaming`,
  `seguro-de-viagem`, `transportes-aeroportos`, `direitos-dos-passageiros`), each with at least
  three official sources, published (`reviewed: true`) at Miguel's request on 2026-10-15, to be
  read again by a second reader; open questions stay as `# TODO Miguel` lines in each front
  matter. To preview: `cd web && npm run dev:fixtures`, then http://localhost:4321/roteiros/ and
  `/dicas/`. The pt-PT review checklist (facts against the sources, no prices, tone, blocks, then
  `reviewed: true` + `last_checked`) is
  [docs/runbooks/rever-conteudo.md](docs/runbooks/rever-conteudo.md).
- **Affiliate blocks (D37):** an itinerary or tip places `<EsimBlock />`, `<InsuranceBlock />` or
  `<ActivitiesBlock />` where it fits in the MDX body (no import: the pages pass them,
  `src/components/mdx-components.ts`) **and** lists the programme in its front matter, e.g.
  `affiliates: [esim, activities]` (a block whose programme is not listed stops the build). Each
  block shows its pt-PT copy with the brand, the tracked link from `affiliates.json` (through
  `cta.partnerLink`: https only, `rel="sponsored nofollow noopener"`) and the block disclosure
  (`labels.json` `disclosure.affiliate`, "Publicidade: esta ligação é um link de afiliado…"); the
  logic is `src/lib/affiliates.ts`. The front matter must read the same for the site and the
  pipeline (`reviewed: true`, not `yes`; known programmes only): shared cases in
  `web/test/fixtures/content-gate-cases.json`. A programme not configured in `config.yaml`
  (insurance today), or an article whose link wasn't created yet, renders **nothing** and the
  build prints `[affiliates] <article>: <programme> block not shown: …`.
- **Scale:** `web/test/scale.test.ts` builds a synthetic dataset the size of the real data
  (`test/synthetic-data.ts`: 360 routes, 6 origins, 156 destinations, `meta.fixture: true`, made-up
  prices only ever shown in a temporary build) and checks page counts, the build-time budget
  (120 s; ~5 s measured for 528 pages), dormant notices, months without data, internal links and
  price traceability at that size.
- **Explorer** `/explorar/` (D31): without JavaScript, the first origin with low prices, every
  destination at its cheapest, by price; with it, a small island (`src/lib/explorer-island.ts`,
  ~5 KB, no framework) adds the filters: origin, maximum budget, departure month, nights range,
  direct only, weekends only (out Friday/Saturday, back Sunday/Monday of the same weekend: 1–3
  nights), pontes. It fetches an
  origin's low prices only when picked, from `/explorar/dados/<ORIGIN>.json` (the contract's rows
  plus the names they need). Server and island share `src/lib/explorer.ts` (rules and result HTML).
  Each result's headline links to its route page (the contract's route `path`).
- **Pontes** `/pontes/<feriado>-<ano>/<origem>/` (paths from `pontes.json`): one page per long
  weekend and origin with the low prices whose departure and return both fall inside the window;
  `noindex` while there are none. A ponte that has passed keeps its page, `noindex`, saying "Esta
  ponte já passou."; titles ("desde o Porto") use the article from config `origins_article`. The calendar is `content/holidays.yaml` (national
  holidays 2026–2027, Código do Trabalho art. 234.º/235.º; add the next year's dates before 2028).
- **Prices:** every price element carries `data-obs` / `data-deal` / `data-route` (also on `<head>`
  when the title shows a price); `web/test/traceability.test.ts` fails on any price string on a
  built page that isn't an amount of the referenced observation, deal or route in the contract,
  JSON-LD included (every `price` and every price string in a block, against the block's own refs).
- **Links:** `web/test/pages.test.ts` fails on any internal link (`a`, `link`, `img`) that doesn't
  resolve to a built page or file; every route page is linked from its origin page and its hub.
- **Booking links** come from the contract as given (never built here); `src/lib/cta.ts` shows a
  button only for a live price with an https link, always with `labels.disclosure.site` next to it.
  Low prices (route pages, explorer, ponte pages, the island) are drawn by one function,
  `src/lib/low-prices.ts`; a row whose partner link is not created yet (per-run link budget) says
  "Ligação de reserva disponível em breve." instead of a button.
- **pt-PT:** formats only in `src/lib/format.ts`, day arithmetic (weekday, nights, Lisbon day of
  an instant) only in `src/lib/dates.ts` (mirrors `i18n_pt.py`: "49,50 €", "sex, 6 nov",
  "12/10/2026 às 22:17" Lisbon time); `web/test/pt-lint.test.ts` fails on Brazilian words
  ("você", "celular", "equipe", …) or English UI text in the templates, and on every itinerary and
  tip (drafts too) also on euro amounts, decimal points ("3.5 km"), ISO or English dates,
  capitalised months ("6 de Novembro"), "20 %", "9 am" and the pt-BR gerund ("estou visitando").
- **Design:** `src/styles/tokens.css` is generated from `docs/design/tokens.json` and replaces
  Tailwind's default colours, fonts, sizes, radii and shadows (`src/lib/tokens.ts` is the same data
  for code: theme-color, the OG image, the review page; no other colour is allowed, a test checks
  it); fonts come from `assets/fonts/`
  through Astro's Fonts API (metric-matched fallbacks), the logo from `assets/logo-light.svg`.
- **CI:** `.github/workflows/web.yml` runs on pull requests touching `web/`, `contract/`, the
  tokens, fonts or logo: `npm ci`, `npm run typecheck`, `npm test`, fixture build, Lighthouse CI (reports kept as an
  artifact). Measured locally on 2026-10-13: performance 0.94, accessibility 1, SEO 1 on all
  three page types; on 2026-10-14 (D30) route 0.91–0.93, origin 0.95, destination 0.95–1 (accessibility,
  best practices and SEO 1), and 0.92–0.98 on the full-size synthetic build's largest pages; (D31)
  the explorer 0.92 / 1 / 1 and a ponte page 0.95 / 1 / 1; (D33) the test itinerary and tip 0.95 / 1 / 1;
  (D34, 12 URLs with `/privacidade/` and `/sobre/`) performance 0.92–0.95, accessibility, best
  practices and SEO 1 everywhere.

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
the deal's link). Its links are created by `export site-data` with `sub_id=site-deal-<id>` and cached
per Project in the database (`meta` key `site.links`, so a CI runner reuses them; an old
`data/site_links.json` is merged in). A website link that fails falls back to the deal's own
tracked link and is retried on the next build. A Project's URL can't change once it joined a
program, so a new domain or handle means a new Project (runbook steps 8–9).

**Low prices** get one link each, for the website Project (falls back to Instagram's), with
`sub_id=site-low-<observation id>`, stored in the `partner_links` table (in the database, so it
survives a CI runner; rows older than 30 days are pruned). A build only asks the API for low
prices without a stored link, biggest discounts first, within one budget per collection run:
`site.max_new_links_per_build` (300 = 30 requests; the API allows 100 requests/min, 10 links
each) for the run's site data export. The rest, and failures, wait for the next full path and
are shown meanwhile without a booking button ("Ligação de reserva disponível em breve.").

**Affiliate blocks** in itineraries and tips (D37) link other Travelpayouts programmes the website
Project is connected to, configured in `config.yaml` (never in code):

```yaml
affiliate:
  programmes:
    esim: {brand: Yesim, url: https://yesim.tech}
    activities:
      brand: Tiqets
      url: https://tiqets.com
      destinations: {PAR: https://...}   # optional: a deeper page for an itinerary of that city
    insurance: null                       # not configured: the block renders nothing
```

`export site-data` creates **one link per (programme, reviewed article that lists it)** through
`PartnerLinksClient` for the website Project, with `sub_id=roteiro-<slug>` or `dica-<slug>` (one
per article: the dashboard shows what each article earns), one API request per article, and
stores it in the database (`meta` key `site.article_links`, with the brand page it was made
for: a new page in config gets a new link; entries of articles no longer published, programmes
no longer listed or configured, and other Projects are dropped on every write). Failures are kept
with their reason, left out of the site and retried by the next full path (the export only runs
there, like the website's deal links; a failed link alone doesn't trigger one). To connect insurance later: join a programme in
Travelpayouts for the website Project, then replace `insurance: null` with its `brand` and `url`
— a config change only (the next run takes the full path, since config.yaml is part of its
fingerprint).

If conversion fails, the deal keeps **no** link. `affiliate_error` explains why, the CLI warns,
and the next render retries. There is deliberately no fallback to a hand-built `marker=` URL,
because Aviasales program term 1.4 only allows network tools.

## Database in Cloudflare R2 (DECISIONS D21)

With the four `R2_*` keys in `.env` (or Actions secrets), the bucket holds everything a run
needs between runs, so any machine (GitHub Actions, the PC) can run the pipeline. Without them
nothing changes: the database is `data/escapadinha.db` and objects live under `data/objects/`.

| Object | What |
|---|---|
| `db/escapadinha.db` | The database: a consistent copy made with the SQLite backup API, integrity-checked |
| `db/escapadinha.json` | Its metadata: `generation` (+1 per push), sha256, `pushed_at`, `pushed_by`, last run id |
| `archive/runs/<run>.json.gz` | Raw API responses per run (D18), written straight to the bucket |
| `backups/<YYYY-MM-DD>/escapadinha.db` | The database before the first run of that Lisbon day |
| `locks/run` | The run lock: `{owner, expires_at}` |
| `review/events/pending/`, `review/events/archive/<YYYY-MM>/` | Review decisions waiting / applied or refused (D26) |
| `review/snapshot.json`, `review/slides/<id>/` | The review queue for any UI, written by every run (D26) |
| `photos/<destination>.jpg` | The Pixabay photo cache (`assets/photos/`), uploaded when fetched (D25) |
| `output/<date>/<deal or guide folder>/…` | Rendered slides, caption, meta (`output/`), uploaded when rendered (D25) |

A runner downloads a photo or a rendered folder the first time it needs it (rendering a slide,
building the site, the review page). The redirect history, the website's partner links and the
last deploy's content hash live in the database (`meta`). The full path of a run on the PC
uploads the photos and rendered folders it made before D25 that the bucket lacks.

`escapadinha run` then does: **lock → pull → daily backup → review events → collect … deploy → review snapshot → push → unlock.**
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

**On your PC** (stats): `store pull` before, `store push` after. `deal check` only reports with
R2 keys (nothing to push). Review decisions
(`review`, `deal approve/reject/published`) go to the bucket as events and need no push; pull first
so the deal you decide on is in your copy (they refuse while the bucket's database is newer).
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
1. Stop the scheduled runs (`gh workflow disable pipeline.yml`: the scheduler Worker and its
   fallback leave a disabled workflow alone, D41) and check that
   `uv run escapadinha store status` shows `lock: free`.
2. `uv run escapadinha store restore 2026-10-13` (dates are listed by `store status`). The current
   local file is kept as `data/escapadinha.db.local-<time>`.
3. Check it (`uv run escapadinha stats LIS-LON`, `uv run escapadinha review`), then
   `uv run escapadinha store push`. It becomes the next generation; runs pull it from then on.
4. Turn the schedule back on (`gh workflow enable pipeline.yml`).

Without the CLI: download `backups/<date>/escapadinha.db` from the R2 dashboard to
`data/escapadinha.db`, then `uv run escapadinha store push --force`.

## GitHub Actions (DECISIONS D25)

`.github/workflows/pipeline.yml` runs `escapadinha run` every 30 minutes, dispatched by the scheduler
Worker (see *Schedule* below, D41), on `ubuntu-latest`: lock → pull the database from R2 → daily
backup → (monthly discovery) → collect → recheck → detect (+ the queue against today's typical
lows, D40) → publish due posts (D32) → **full path
only when needed** → push → unlock.

- **Fast path, full path.** After detection the run compares a fingerprint of what the public
  outputs show with the one stored at the last full path (from the export it deployed, not
  re-read afterwards): promotions (id, status, link), the
  site data exactly as the next build would read it (computed in memory, without the run id,
  timestamps and counters no page shows), routes (key, status, name), the Lisbon date, and the
  code, config and content (the Python package, `config.yaml`, `content/`, the web package's
  sources and lockfile, the logo and fonts). If anything changed it takes the full path (render new deals → approve by the
  rules (D46) → export the site data → `site build` (Astro) → deploy when the content changed); otherwise it ends there.
  One exception (D46): a live promotion's "verificado a" moves on every recheck, so when the site
  data is the *only* change the site is rebuilt at most every `site.refresh_min_gap_minutes`
  (120). The log says which and why:
  `Path: fast (nothing the site shows changed)`, `Path: fast (site data changed, rebuilt at most
  every 120 min (last full path 40 min ago))`, `Path: full (changed: promotions, site data)`,
  `Path: full (forced with --full)`. A full path that fails records nothing, so the next run
  tries again. The first run after Lisbon midnight is always full, so typical lows and
  "Atualizado a" are at most a day old.
- **Duration and status.** Every run ends with `Run ok in 1 min 52 s.` and writes the same to the
  run's summary page (status, duration, collection counts, path and reason). A failing route or
  month is listed and the run goes on (`partial`); only a collection where every request failed
  fails the job (exit 1). The database is pushed in every case.
- **No overlap.** `concurrency: pipeline` queues a run behind the one in progress (never cancels
  it); the R2 lock also keeps the PC out. Job timeout 45 min, below the lock's 60 min.
- **Caches.** uv's cache (setup-uv) and the Chromium download (`~/.cache/ms-playwright`, keyed on
  `uv.lock`). Chromium and its system libraries are installed only when slides are rendered
  (`ESCAPADINHA_INSTALL_BROWSER=1`: `playwright install --with-deps chromium` the first time a
  renderer opens), so the fast path never pays for it. Node 22 for the full path's `npm ci`, the
  Astro build and `npx wrangler`; the fast path never runs npm. npm's download cache (`~/.npm`,
  keyed on `web/package-lock.json`) is restored on every run (a few seconds) and saved only after
  a full path that ran `npm ci` on a cache miss (`npm_ci=true` in `$GITHUB_OUTPUT`, D35).
- **Secrets:** repo → *Settings* → *Secrets and variables* → *Actions* → *New repository
  secret*, one per `.env` key: `TRAVELPAYOUTS_TOKEN`, `TRAVELPAYOUTS_MARKER`, `PIXABAY_API_KEY`,
  `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, and optionally `INSTAGRAM_ACCESS_TOKEN`,
  `INSTAGRAM_ACCOUNT_ID` (unset: due Instagram posts wait, D36). They reach the run as
  environment variables (there is no `.env` on the runner); GitHub masks them in logs and the
  workflow never prints them.

**Run it by hand:**
- Web: *Actions* → *Pipeline* → *Run workflow* (tick *Full path* to render, build and deploy
  even when nothing changed).
- Terminal:
  ```bash
  gh workflow run pipeline.yml                # like the schedule: the run decides fast or full
  gh workflow run pipeline.yml -f full=true   # full path
  gh run watch                                # follow the run that just started
  gh api repos/MiguelCorre/escapadinha/dispatches -f event_type=full-run   # like the review Function's review-decision
  ```
  `repository_dispatch` events of type `review-decision` or `full-run` always take the full path.

### Schedule (DECISIONS D41)

GitHub's own cron is best effort (the 2-hourly one fired 4.4–6.8 h apart), so `pipeline.yml` has
no `schedule`. Every routine run is a `workflow_dispatch` with `full: false`:
- **The scheduler Worker** (`workers/scheduler/`, Cloudflare Workers free plan): a Cron Trigger
  `17,47 * * * *` (UTC, every 30 minutes since D46; 2-hourly before) dispatches `pipeline.yml` on
  `master`, unless a run of it was created in the
  last 20 minutes (a review decision, a manual run, the fallback) or the workflow is disabled. One
  line per tick in its Workers Logs: dispatched, skipped (and which run served the tick), or why
  the dispatch failed. The token is the Worker secret `GITHUB_ACTIONS_TOKEN` (fine-grained,
  this repository only, Actions: Read and write); it never reaches a log.
- **The fallback** (`.github/workflows/pipeline-fallback.yml`): GitHub's cron every 6 h runs the
  same tick with Node and its own `GITHUB_TOKEN`, and dispatches only when no run started in the
  last 3 h, i.e. when the Worker missed its runs. Then the job fails on purpose, so GitHub e-mails
  you. With a working Worker it never dispatches (a skipped tick leaves at most 50 min).
- **The run log** warns when the previous collection started more than 2 h before this run:
  `Warning: the previous run (#57) started 5 h 07 min ago, more than 2 h: the half-hourly schedule
  missed runs. …` (also in the run's summary). It also warns when the last daily pass is more
  than 30 h old (D42, see *What a run collects*).
- **Pause everything:** `gh workflow disable pipeline.yml` (the Worker and the fallback skip a
  disabled workflow); `gh workflow enable pipeline.yml` to resume.
- **Deploy (by hand, rarely):** from `workers/scheduler`, `npx --yes wrangler@4.149.0 login`, then
  `npx --yes wrangler@4.149.0 deploy`, and once `npx --yes wrangler@4.149.0 secret put
  GITHUB_ACTIONS_TOKEN`. The pipeline's Cloudflare token can only deploy Pages, so there is no CI
  job for it. Step by step, with the token and the check: **[docs/runbooks/agendamento.md](docs/runbooks/agendamento.md)**.
- **Tests:** `node --test` in `workers/scheduler` (no dependencies; `uv run pytest` runs it too).

**Minutes used.** A private repo on GitHub Free gets 2000 Linux minutes a month (public repos are
not metered), and **GitHub rounds each job up to the whole minute**. Measured on 10-13..15,
before the daily pass (1,080 requests a run): a pipeline run took 1.7–3.4 min of wall time and
billed 2–4 minutes (one took 6.2 and billed 7), 3.2 on average. With D42 a day has one pass of
2,160 requests (~4 min of them, ~5 billed) and 11 regular runs of 717 (about a third shorter,
~2.2 billed), so the 2-hourly pipeline used ≈ **1000 min/month**. **With the 30-minute runs
(D46) it is 48 runs a day, about 3 200 min/month**, over GitHub Free's 2 000: before deploying
the Worker's new cron, set a spending limit for Actions (account → *Settings* → *Billing and
licensing* → *Spending limits*; about 10 USD/month at 0.008 USD per Linux minute), or the
pipeline stops when the quota ends. The rebuild throttle keeps most runs on the fast path
(~2 min); the fallback's checks (≤ 4 a day, 1 min each) and the Web CI on pull requests
(7–10 min a run) come on top. Out of minutes, GitHub stops Actions in a private repo until the
month ends, and the pipeline with it: D41 lists the knobs.
- One run: *Actions* → the run → *Usage* (under *Run details*) shows its billable time; the
  summary shows our own `Duration`.
- The month: your account → *Settings* → *Billing and licensing* → *Usage*, filtered on Actions.
- `gh run list --workflow pipeline.yml --limit 12` lists the last day's runs with their elapsed time.

**PC task: retired.** The Windows scheduled task was retired on 2026-10-15 (#43). The script
below stays for emergencies (it takes the same R2 lock, so it never overlaps a run on Actions);
`Get-ScheduledTask -TaskName "Escapadinha collect"` reports that no such task exists.

## Scheduling on the PC (Windows Task Scheduler, retired)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1                # every 2 h, all day
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -EveryHours 1
powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Unregister
```
Each run takes about 2 minutes (8 requests at a time, D24; the day's pass about 4) and makes one
API call per asked route and month (D42, at 360 routes: 2,160 on the day's pass, ~717 on the
others; plus ~25 once a month for discovery). Runs missed while the
PC sleeps start when it wakes. Output is appended to `logs/run-<date>.log`, ending with
`---- exit N ----`.

## Guides ("guia rápido")

The website's tips and itineraries are MDX in `web/src/content/` (see "The Astro package", D33);
the YAML guides below only feed the Instagram carousel (`render guide`); the old Jinja site's
`/guias/<slug>/` URLs 301 to the tip naming them in `legacy_path`. Add `content/guides/<slug>.yaml` with a title, 3–8 tips, CTA, caption and hashtags (see the
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
  if it is stale or a colour pair drops below WCAG AA), then `npm run tokens` in `web/` for the
  Astro site's Tailwind theme and `TOKENS` module (`test_web_tokens.py` fails until you do).
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
- `test_actions.py` drives `escapadinha run` as Actions does (fast/full path, a failing route,
  the step summary) and builds the site on a "fresh runner" that only has the bucket, checking
  it is byte-for-byte the PC's site (npm faked: `test_web_build.FakeNpm` writes a page per
  contract path); `test_workflow.py` checks the workflow file (triggers,
  concurrency, timeout below the lock TTL, secrets never printed).
- `test_scheduler.py` (D41): the scheduler Worker's `wrangler.toml` against the workflows it
  dispatches, the fallback workflow, the skip windows against the run log's 3 h warning, and
  the warning itself; it also runs the Worker's own `node --test` (skipped without Node): the
  dispatch request, the skip rules and the token never logged, on a fake GitHub.
- `fixtures/discovery/` holds real catalogue and supplement payloads recorded on 2026-10-13,
  trimmed to the rows the tests need (`RECORDED.txt` lists the URLs and what was kept).
- `fixtures/schema_v5.sql` and `schema_v7.sql` are older schemas, to test the upgrades.
- `test_graphql.py` (D43): the GraphQL client (token, trip window, a 429 waits, the 60/min limiter
  under 8 workers) and the pure offer match on the probe's real row shape; `test_enrich.py`: a run
  enriches only its matched low prices and candidates, never a price, archives the answers under
  an `enrich` run, keeps unmatched offers unknown, and the v13 → v14 upgrade.
- `test_demand.py` (D45): the JSON-stat parser on the real Eurostat answer saved in
  `fixtures/eurostat_avia_par_pt.json` (missing cells skipped), partner airports summed into a
  city, the twelve-month window and the zero months, the rank, the client, the discovery that
  stores the figures and archives the answer (a failed fetch reported, the old figures kept), the
  day's pass narrowed by rank (plan and `run_collect`), the v15 → v16 upgrade and the export.
- `test_backtest.py` (D44): the detector backtest on a synthetic database: the copy is
  read-only, run selection by id or by day, one flag per candidate, the 24 h recheck and the
  hindsight check, the new-low rule, the presets, the Markdown and JSON, `--state` and the script.
- `test_traceability.py` (normal run, no browser) builds a database with promotions (live,
  expired, new), low prices and typical lows, renders every caption, and fails
  on any price string that isn't a referenced observation's price, a referenced deal's stored
  baseline or recheck price, or a typical low computed from the referenced route's observations.
- `test_site_data.py` validates the JSON export and the committed fixtures against
  `contract/site/v1/*.schema.json`, traces every price in the export the same way (a guard fails
  when a schema gains a price field the checker doesn't know), and tests the size budget.
- `test_affiliate_blocks.py` (D37): the affiliate blocks' links through the export with the
  partner links API mocked (one per programme and reviewed article, sub_id per article, created
  once, a city page from config, failures retried, drafts and test-only entries left out, stale
  links pruned), the programme config's validation, the shared front matter cases
  (`web/test/fixtures/content-gate-cases.json`, also checked by `web/test/content.test.ts` with
  the zod schemas and Astro's YAML parser), and that the hand-added `affiliates.json` and
  `disclosure.affiliate` fixtures are what the export writes for the fixture content.
  `web/test/affiliate-blocks.test.ts` checks the rendering on the fixture build (eSIM and
  activities shown where placed, insurance absent with the build's warning) and on the
  configured build (insurance with a fake brand; activities configured without a link: absent,
  with a warning).
- `test_web_tokens.py` fails when `web/src/styles/tokens.css` or `web/src/lib/tokens.ts` no longer
  matches `docs/design/tokens.json` (run `npm run tokens` in `web/`).
- `test_web_build.py`: `site build` (npm ci only when needed, the export's path, promotion
  images, `_redirects`/`_headers` for renamed, dropped and old guide pages, config rules, the
  full path's time budget with a fake clock and subprocess) and
  `site deploy` (from `web/`, refuses a fixture build, skips a rebuild that only moved
  timestamps), with npm and wrangler faked.
- The web package has its own tests: `cd web && npm test` (see "The Astro package"), including the
  review Function's (`web/test/review/`: Access token checks, events validated against
  `contract/review/v1/event.schema.json`, the dispatch, the page).
- `test_live_check_cases.py` and `web/test/review/live-check.test.ts` run the same cases
  (`contract/review/v1/fixtures/live-check-cases.json`) through the pipeline's live check and the
  Function's port: both must agree, on prices, stop counts, the pt-PT reason shown when the
  provider fails (rate limit, HTTP error, error payload, no answer, no token) and the request
  itself (`queries`: `direct=true` on nonstop-only routes, D39).
- `test_review_rules_cases.py` and `web/test/review/rules.test.ts` check `review.py`'s tables and
  `check_decision` and the Function's `rules.ts` against `contract/review/v1/fixtures/review-rules.json`.
- `web/test/colours.test.ts` fails on a raw colour (hex, `rgb()`, `hsl()`) in `web/src/` or
  `web/functions/` outside the generated `tokens.css` / `tokens.ts`.
- `test_crawl.py`: the crawl against a build and the live site (respx), and the cutover's check:
  the real Astro build (npm) from a database with the old site's redirect history, the old
  sitemap's URLs (`docs/cutover/`) plus an expired promotion and a Jinja guide, every one a page
  or a 301 to one (skipped without `web/node_modules`).
- `test_review_function_deploy.py`: `site deploy` uploads the Function with the Astro build, a
  Function change redeploys and takes the full path.
- `test_posting.py`: slot allocation and the daily cap with an injected `now` (summer/winter time,
  both clock-change Sundays, Lisbon vs UTC midnight), the upgrade from `schema_v5.sql`/`schema_v7.sql`,
  queueing on an applied approval, the publish step (dry run, expiry/rejection cancels, waiting
  for a recheck, publisher errors, one Instagram post per run), `queue list` and the run order.
  The WhatsApp text is checked in `test_captions.py` and by the traceability test.
- `test_instagram.py` (D36): the Instagram publisher through `run_publish` with the Graph API and
  the site's HEAD answers mocked by respx (a fake Graph that keeps containers and media):
  carousel then story, status polling of children and carousel (IN_PROGRESS → FINISHED with
  backoff, still in progress → wait and resume, ERROR → retried with new containers), the
  publishing limit, images not yet deployed → wait, behind an https redirect → live, an http one
  → not, still missing a day after the slot → failures until cancelled, a crash between publish
  and recording → adopted by caption (the first attempt's, even if the rendered text changed),
  never reposted, story failure and the story window, error mapping (cancel/wait/retry), invalid,
  refused (190 on any call, Facebook Login) and expired tokens, refresh (< 10 days → refreshed,
  ≥ 10 → not; unknown expiry → after a day; a stored token refreshed in turn), the stored token
  and its notice, Facebook Login's host, missing secrets → wait (not a dry run), the `published`
  decision, `instagram token`. The schema v11 upgrade and the story-status CHECK are in
  `test_posting.py`.
- `test_telegram.py` (D38): the Telegram publisher through `run_publish` with the Bot API and the
  site's HEAD answers mocked by respx: the photo message (cover JPEG, WhatsApp text, message id
  and t.me link, no `published` decision), the cover not deployed yet → wait, then failures after
  a day, 429 → wait, 401 → wait with a notice, refused channels (400/403) → wait with a notice
  until a message goes out, a photo Telegram couldn't fetch and 5xx → retried, a lost answer
  (read timeout, protocol error, a proxy's 502 page) → cancelled and never resent, no connection
  → retried, a send record adopted after a lost database or cancelled without its answer, the
  1024 UTF-16 caption limit, the token in no log, reason, database row or stored object,
  `queue retry` (local at once, with R2 by the next run, refused without a lost send, never
  requeueing a later cancellation), the link in `queue list` and `deal check`, the config
  validator, the publisher registry, a malformed or missing channel secret → wait (the run still collects). The
  error texts follow the Bot API's (refused channel → wait, permanent → cancel, transient photo
  → retry). The schema v12 upgrade is in `test_posting.py`.

## Data sources and terms

- **Travelpayouts / Aviasales Data API**: a cache of prices users found recently (not live).
  The limit is 600 req/min on v3 endpoints, 60 req/min on the GraphQL endpoint (`/graphql/v1/query`,
  used only to enrich stored offers with baggage and agency, D43; same cache, same terms). Route discovery also reads the public data files
  (`data/routes.json`, `data/airports.json`, `data/pt/cities.json`) and `v1/city-directions`.
  Each item's link carries `search_date`, the day a
  user found the price, which can be several days old. Captions state both that date and when
  we checked it, and that prices change. Times are UTC, so trip dates are taken from the link's
  local dates.
- **Eurostat `avia_par_pt`** (D45): passengers carried per month on each airport pair with a
  Portuguese airport (compiled by INE from ANA and ANAC data), through the public dissemination
  API (JSON-stat, no key, one request a month). Eurostat's copyright notice authorises reuse of
  its statistical data for commercial and non-commercial purposes provided the source is
  acknowledged: the site's "Como funciona" page says "Dados de passageiros: Eurostat,
  avia_par_pt, reutilização autorizada com indicação da fonte". Used for demand only, never for
  prices. ANAC's and ANA's own publications allow no reuse and are not read (research A13).
- **Pixabay**: free commercial use under the Pixabay Content License. The API forbids
  hotlinking, so photos are downloaded once and cached, and every caption credits the
  contributor. Standard keys get `largeImageURL` (max 1280 px, slightly upscaled to
  1080×1350). Approved full API access unlocks `fullHDURL`, which is used automatically.
- Affiliate disclosure ("Publicidade · … links de afiliado …") appears on every deal caption
  and on the CTA slide.

See [DECISIONS.md](DECISIONS.md) for why these were chosen and the v2/v3 roadmap, and
[LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) for what must happen before the first public post.

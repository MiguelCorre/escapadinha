# Decisions

## D1: Price source: Travelpayouts / Aviasales Data API (2026-10-12)
Options were reviewed in October 2026:
- **Amadeus Self-Service** was shut down on 2026-07-17.
- **Kiwi Tequila** has been partner-only since 2024.
- **Skyscanner** is for approved high-traffic partners only and reportedly forbids caching.
- **Duffel** is open, but every search is billed at $0.005 when there are no bookings
  (about $100+/month for daily collection).

Travelpayouts is free, has open signup, is designed for content sites, and pays a
commission through the affiliate marker.
**Trade-off:** the data is a cache of recent user searches, not live. We store `fetched_at`
and the raw item, treat only the latest run as deal candidates, and every caption says when
and where the price was found.

## D2: Never fabricate prices
Observations are only built from API payloads. Items with no return date or no positive
price are dropped, not patched. There is no demo/seed command: tests use synthetic data in
temp directories only. Deals reference `observation_id` (UNIQUE), and `meta.json`
repeats the trace.

## D3: Detector: typical low per route and month (revised 2026-10-12)
- The first version used the median of all fares per route. On real data it flagged 9 of 10
  routes, because a route's cheapest dates always look 40–60% "below" that median.
- Now:
  - **Baseline:** the median of daily lows (each day's cheapest found price) per route and
    departure month.
  - **Deal:** a fresh price ≤ (1 − threshold) × baseline.
  - **Sorting:** biggest discount first.
- Days are keyed by `found_date`, so the first fetch already holds about a week of baseline
  days. The user chose this so deals can start immediately.
- Candidates are days inside `max_offer_age_days`, and the baseline uses only older days,
  so a candidate never lowers its own baseline.
- The baseline is "insufficient" below `min_baseline_days`. During that time only an
  explicit per-route `price_cap_eur` can flag a deal.
- Known bias: the cache keeps fewer old prices, so early baselines are a little noisy. Our
  own runs fill this in over time.

## D4: Round-trips, 2–10 nights, 3 departure months
Matches the "ida e volta desde X €" format. One API call per route per month returns the
cheapest round-trips. We filter by nights locally.

## D5: Photos: Pixabay, downloaded and cached (revised 2026-10-12)
The plan picked Pexels, but its API page says "New API key issuance is currently paused".
Pixabay replaced it:
- Free key, 100 req/min.
- The Content License allows commercial use and modification.
- The API forbids permanent hotlinking, so images must be downloaded, which fits pre-rendered PNGs.

Unsplash was rejected because its API rules require hotlinking and download-event pings.
Contributor credit is stored and printed in every caption even though the license doesn't
require it. Trade-off: standard keys get at most 1280 px images (`fullHDURL` needs approved
full access).

## D6: Rendering: HTML/CSS + Playwright, assets as data URIs
Templates are plain HTML/CSS that a designer can edit. Photo, font and logo are inlined so
rendering works offline from `about:blank`. Long text shrinks via a small `fitText()` JS
helper. All slides are 4:5 (1080×1350) because Instagram crops carousel items to the
first item's ratio.

## D7: Fonts: system fonts by default, no bundled download
Headlines use Bahnschrift or Segoe UI Black. `assets/fonts/display.ttf` (OFL) is picked up
when present. This keeps the repo free of third-party font binaries until a brand font is chosen.

## D10: Found date vs fetched date (2026-10-12)
The first real response showed that `prices_for_dates` returns prices users found up to about
7 days earlier (the link's `search_date`), not only the last 48 hours. We store `found_date`
(schema v2). Captions say "encontrado a <found> … verificado a <fetched>". The detector skips
offers older than `max_offer_age_days`. API timestamps are UTC, so local trip dates are read
from the link path (`LIS1811LON2211` → 18/11, 22/11) with UTC as the fallback.

## D11: Always name the arrival airport (2026-10-12)
The first real deals to Paris all landed at Beauvais (BVA), about 80 km away. Deals show the
arrival airport on slide 2 and in the caption. Airports listed in `i18n_pt.REMOTE_AIRPORTS`
(BVA, BGY, …) also appear in the headline and on the cover.

## D9b: Collection every 2 hours (2026-10-12)
To catch deals before competitors, the task runs every 2 h around the clock (12 runs/day,
360 API calls/day against a 600/min limit). The runner goes through cmd.exe because
PowerShell 5.1 turns uv's stderr progress into errors.

## D12: Aviasales program terms, checked 2026-10-12
- **Allowed:** "Content creation: any channels", which covers Instagram. Reward is 1.1–1.3%
  with a 30-day cookie.
- **Not allowed:** paid search and media buying. Using the brand in PPC, or PPC linking straight
  to Aviasales, gets the account blacklisted (term 1.2).
- **Marker:** 789000 is the account ID. The dashboard puts `marker=789000` in its own links.
- **Project:** ID 584711 for https://www.instagram.com/ondestaanocas/ (created 2026-10-12).
  Its channel URL is locked once connected to programs; a renamed handle needs a new project.
- **Resolved:** term 1.4 allows only the network's own promo tools. Deals now get links from the
  partner links API (`POST /links/v1/create`, trs=584711, sub_id=deal-<id>), stored in
  `deals.affiliate_url` (schema v3). Failures are recorded with no fallback to a hand-built
  `marker=` URL.

## D13: Portuguese audience, recheck, direct only, no scraping (2026-10-12)
- **aviasales.pt:** aviasales.com defaults to USD/English/lb/AM-PM even from Lisbon.
  aviasales.pt shows EUR and EU formats (the UI is English or Russian only). The collector uses
  `market=pt`, and links go to aviasales.pt; the partner links API accepts .pt URLs.
- **Alternatives checked:**
  - Kiwi.com data API needs 50k MAU.
  - Skyscanner (Impact) needs about 5k visits/month and manual approval.
  - eDreams/Opodo (Awin) and KAYAK need applications and give no price data.
  - Only Aviasales gives free price data, and the price shown must come from the same place as
    the link. Revisit Skyscanner once the website has traffic.
- **Recheck:** cached prices moved within 2 hours (OPO-PAR 60 → 70 €). Open deals are
  re-verified on every run and expire when the trip is no longer offered at or below the
  deal price, or the price is no longer fresh.
- **direct_only:** a "Lisboa → Paris 91 €" deal returned via Beauvais → Milan-MXP, then
  self-transfer to Bergamo → Lisbon, sold by an agency. Deals and baselines now use nonstop
  round trips only (configurable).
- **No scraping:** Skyscanner, Kiwi, eDreams, Google Flights and airlines forbid automated
  collection. Ryanair actively litigates (CJEU Ryanair v PR Aviation, 2015), and bypassing bot
  detection is off-limits. Legitimate routes to more data: the Aviasales Search API (approval),
  Duffel (paid, live, no Ryanair), Skyscanner affiliate, manual review before posting.

## D14: Approval queue (v2, 2026-10-12)
- A local FastAPI page on 127.0.0.1 with no login. It only runs on this PC, while
  `escapadinha review` is open.
- The rules live in `review.py` and `pipeline.py`, so the CLI and the page can't disagree.
- **Approve = live price check + approval:** the cache moved 60 → 70 € within hours on day one.
  A live check costs one API call (route and departure month), and its prices are stored as a
  `live_check` run that is excluded from "latest full run".
- **Statuses:** `published` is set by hand until Instagram publishing exists (next v2 step).
- **Schema v5:** `fetch_runs.scope`, plus deal `output_path`, `reviewed_at`, `review_note`,
  `published_at` and `post_url`.

## D15: Website (v3, 2026-10-13)
- **Choices (by the user):**
  - Brand "Onde está a Nocas?", matching the Instagram account.
  - Cloudflare Pages on the free `*.pages.dev` subdomain (.pt later).
  - The site shows approved and published deals while they're valid.
- **Static generation from SQLite with Jinja,** the same stack as the slides. There's nothing
  to host or patch, and the site is rebuilt on every collection run.
- **Deploy:** wrangler Direct Upload (pinned version). It skips the upload when the content
  hash is unchanged, ignoring the build timestamp, to avoid a deployment every 2 h with the
  same deals.
- **Trust rules carry over:** only human-approved deals. Expired pages stay but are
  `noindex` with no CTA. Every page shows when the price was found and checked, and has the
  affiliate disclosure. Route pages publish only typical lows backed by
  ≥ `min_baseline_days` days of data.
- **Project creation via REST API:** `wrangler pages project create` (4.149) delegated a missing
  project to the Workers flow, which auto-detected the repo as a Hugo site and failed.
  `site setup` now calls `POST /accounts/{id}/pages/projects`. wrangler only does `pages deploy`,
  and it runs inside `site/` so it never scans the repo. The token is user-scoped with
  "Cloudflare Pages: Edit" only.
- **No cookies of our own;** analytics are optional via Cloudflare Web Analytics (cookieless).
- **Brand hashtag** comes from the handle (`#ondestaanocas`), not the display name.

## D8: Stack
Python 3.14 via uv (latest stable), typer, httpx, pydantic-settings, stdlib sqlite3
(plain SQL, `PRAGMA user_version` for schema versioning), jinja2, playwright, pytest + respx.

## D9: Scheduling: Windows Task Scheduler
Runs `escapadinha run` 3×/day on this PC with daily log files. The SQLite DB stays local,
so nothing has to be hosted.

## Roadmap
- **v2: approval queue (done, D14) + Instagram publishing (next).**
  - Review step moves deals `rendered → approved/rejected`.
  - Optional Duffel live re-check before posting.
  - PNG → JPEG (the Graph API accepts JPEG only), uploaded to public storage (R2/S3).
  - Graph API carousel (≤10 items, caption on the parent container) and a Story from slide 1.
  - Needs: an Instagram professional account, Business Login with
    `instagram_business_content_publish`, and `/content_publishing_limit` checks
    (100 posts/24 h). Confirm the Standard vs Advanced access needs at the start of v2.
- **v3: website (live at ondestaanocas.pages.dev, D15) + hotels.**
  - Static site generated from the DB (Cloudflare Pages) with per-route SEO pages.
  - Hotels: redo the API research then.

## D16: Brand name "Ponto Nómada" (2026-10-13)
- **Decided by Miguel** from a sketch by his partner: name **Ponto Nómada**, tagline
  "A Nocas pelo mundo, o mundo ao teu alcance.", positioning "Viagens · Inspiração · Experiências"
  (aspirational concept: mountains mark, serif-ish display type, sunset/sea imagery).
- "Onde está a Nocas?" was the placeholder; the Instagram handle `@ondestaanocas` stays until Miguel
  renames the account (a renamed handle needs a new Travelpayouts Project, see D9).
- Availability checked 2026-10-13: `pontonomada.com` free (Verisign RDAP 404); `pontonomada.pt` and
  `ponto-nomada.pt` have no DNS, registry confirmation pending in the brand runbook (issue #22);
  Instagram `@pontonomada` and `@ponto.nomada` show no profile.
- **Consequences:** `brand.name`/`brand.tagline` in config drive the site and slides; `site.base_url`
  and the Cloudflare project stay on `ondestaanocas.pages.dev` until the domain is connected (#22 → #23).


## D17: Routes as data (2026-10-13, #2)
- **Why:** "all flights from Portugal" is ~300 direct routes plus long-haul, and the list must
  maintain itself (discovery, dormancy). A static config list cannot do that.
- **What:** schema v6 adds a `routes` table (origin, provider city code, `city_pt`, `kind`
  `europe`/`long_haul`/`domestic`, nullable rule overrides, `status` `active`/`dormant`,
  `discovered_at`, `last_observed_at`). It is the source of truth; the collector, detector,
  recheck, live check, website and photos all read it.
- **Config only shapes it:** per-kind defaults, per-route overrides, exclusions, the long-haul
  list, and a `seed` inserted once into an empty table (the 10 original routes, kind `europe`,
  so behaviour is unchanged). `routes.sync` runs on every command: it seeds, adds long-haul
  routes and mirrors the overrides into the table (no override = NULL = kind default).
- **Rules:** `europe` and `domestic` are nonstop both ways, 2–10 nights (as before, D13).
  `long_haul` allows 1 stop each way and 7–21 nights (spec #1). The nights range is applied by
  the collector and again by the detector, so offers stored under an older range never enter
  a typical low. Unknown transfer counts never pass a stop limit.
- **Excluded routes** are not seeded and not collected; a route excluded later stays in the
  table (its page and history are kept).

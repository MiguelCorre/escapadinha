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
  - **Deal:** a fresh price ≤ (1 − threshold) × baseline (and, since D24, ≥ `min_saving_eur`
    below it; lower tier "low price" at `low_threshold`).
  - **Sorting:** biggest discount first.
- Days are keyed by `found_date`, so the first fetch already holds about a week of baseline
  days. The user chose this so deals can start immediately.
- Candidates are days inside `max_offer_age_days`, and the baseline uses only older days,
  so a candidate never lowers its own baseline.
- The baseline is "insufficient" below `min_baseline_days`. During that time only an
  explicit per-route `price_cap_eur` can flag a deal. (Since D40 promotions need their own,
  stricter maturity, and only days with two departure dates count.)
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

## D7: Fonts: system fonts by default, no bundled download (replaced by D22, 2026-10-13)
Headlines use Bahnschrift or Segoe UI Black. `assets/fonts/display.ttf` (OFL) is picked up
when present. This keeps the repo free of third-party font binaries until a brand font is chosen.
**Replaced:** the brand fonts are chosen (D20) and self-hosted as WOFF2 in `assets/fonts/` (D22);
`display.ttf` is no longer read.

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
- Domain, redirects and per-channel Projects: D19.

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

## D18: Observations stored once, raw responses archived per run (2026-10-13, #3)
- **Why:** the source is a cache, so every 2-hour run returns mostly the same offers. On the
  real database 6644 rows held 606 distinct offers (most seen in 13–15 runs); at ~300 routes
  that would be ~170k rows/day, and `raw_json` was most of the 9.4 MB.
- **Identity:** (source, origin, destination, departure_at, return_at, airline, flight_number,
  price, found_date). The UTC timestamps come from the API item (`departure_at`/`return_at`
  columns); `found_date` is part of it, so a new search of the same price is a new observation.
- **Repeat:** `last_seen_at`, `last_run_id`, `seen_count` (+1 once per run). `run_id` and
  `fetched_at` stay the first sighting, so traceability points to the first run's payload.
- **A run's prices** = offers with `last_run_id >= run`. Detection skips offers that already
  have a deal (any status): the same row can come back after its deal expired.
- **Raw archive:** one gzip JSON per run (request params without the token + verbatim payload)
  behind `ObjectStore` (get/put/list/delete/lock), local directory now, R2 in #4 with the same
  contract tests. A failed archive write marks the run `partial` with the error.
- **Migration 7** keeps every deal's observation id, sums sightings into `seen_count`, and
  archives the old `raw_json` per run as `reconstructed` objects (items grouped per route, as
  whole responses were never stored). Result on the real DB: 9.4 MB → 0.65 MB + 0.8 MB archives.

## D19: Domain `pontonomada.pt`, host redirect, one Travelpayouts Project per channel (2026-10-13)
- **Domain:** `pontonomada.pt` is the canonical domain (registered by Miguel on 2026-10-13 at **PTisp**,
  4,91 € the first year, 22,76 €/year renewal incl. VAT; cheapest of PTisp, OVHcloud 20,90/16,47 €,
  Amen 48,59/48,59 €; Hostinger doesn't sell .pt; Cloudflare doesn't sell .pt; WHOIS kept private). `pontonomada.com` is optional and only redirects.
  Config: `site.domain` names it; the switch itself is one line, `site.base_url`. The Pages
  project keeps the name `ondestaanocas` (Pages projects can't be renamed).
- **Host redirect = an account-level Cloudflare Bulk Redirect**, set up by hand (runbook step 6):
  `ondestaanocas.pages.dev` (include subdomains, so per-deploy `<hash>.` URLs too),
  `www.pontonomada.pt` and the `.com` → `https://pontonomada.pt`, 301, preserving path and query.
  Why: Pages `_redirects` only matches paths, never the host; Bulk Redirects are what Cloudflare
  documents for `*.pages.dev` → custom domain, work for hostnames outside our zones, are free
  (Free plan: 15 rules, 10 000 URLs) and run before Pages, so they cost no Worker requests.
  Rejected: a Pages Functions `_middleware` checking `Host` (code on every request, counts
  against the Workers free quota, and `_redirects`/`_headers` stop applying to Function
  responses); zone Redirect Rules (`pages.dev` isn't our zone).
- **Generated by the build** (`website/redirects.py`), deployed with the site:
  - `_headers`: `X-Robots-Tag: noindex` for every `site.legacy_hosts` entry that isn't the
    `base_url` host, and for `<hash>.<project>.pages.dev`. Listing the current host in
    `legacy_hosts` is harmless (it's skipped), so the switch stays a one-line change and search
    engines drop the old host even before the Bulk Redirect exists.
  - `_redirects` (301): `site.redirects` from config, every path a page was published at before
    (kept in `data/site_paths.json` by stable key: deal id, route key, guide slug), so renamed
    slugs keep working, and short `/promos/<id>` aliases. Pages applies `_redirects` before
    files, so a rule whose source is a current page is never written (config ones are reported).
    Removed pages (e.g. a dropped route) aren't redirected: an honest 404. Max 2000 rules.
- **One Travelpayouts Project per channel** (`affiliate.projects: {instagram, website}`), because
  a Project's URL is fixed once it joins a program. Captions, slides and `meta.json` use
  `instagram` (falls back to the old `affiliate.project_id`); the website uses `website`, falling
  back to the Instagram one. Website links still come only from `PartnerLinksClient`
  (`sub_id=site-deal-<id>`) and are cached per Project in `data/site_links.json`, not in the DB, to
  avoid a schema change while #2 changes the schema. A failed website link falls back to the deal's
  stored tracked link (Instagram Project) and is retried on the next build; never a `marker=` URL.
- **Order matters:** website Project only after the domain is live; Instagram rename together
  with its new Project and `brand.handle`; keep Project 584711 while live deals use its links.
- **Progress 2026-10-13 (with Miguel, built-in browser):** zone `pontonomada.pt` added to Cloudflare
  (Free plan, no DNS records yet, AI crawler defaults left as recommended); `.pt` active at PTisp,
  DNSSEC off, nameservers set to `laura.ns.cloudflare.com` / `rene.ns.cloudflare.com`. Pages custom
  domain (runbook step 4) waits until Cloudflare reports the zone active.
- **Progress 2026-10-13 evening:** the `.pt` registry took the new nameservers (PTisp showed them saved
  before DNS.pt published them) and the zone went active. Pages custom domains `pontonomada.pt` and
  `www.pontonomada.pt` added (step 4; Cloudflare created the proxied CNAMEs). `site.base_url` is now
  `https://pontonomada.pt`, `www.pontonomada.pt` joined `legacy_hosts`; built and deployed with
  `--force` (step 5): canonical links and `sitemap.xml` use the new domain and `ondestaanocas.pages.dev`
  answers `X-Robots-Tag: noindex`. Bulk Redirect (step 6) live the same evening: list
  `pontonomada_hosts` (`ondestaanocas.pages.dev` incl. subdomains, `www.pontonomada.pt`; 301, query, subpath
  and path suffix kept) enabled by rule "Dominios antigos para pontonomada.pt"; checked with curl
  (`/voos/lisboa-londres/?x=1`, a per-deploy `<hash>.` host and `www` all 301 to the same path on
  `pontonomada.pt`). Website Travelpayouts Project (step 8) the same evening: "Pontonomada" **585209**
  for `https://pontonomada.pt`; Aviasales was available to it right away (no separate join). Route pages'
  low-price buttons now carry links created for 585209 (`partner_links`), checked on the live site.
  #22 closed on 2026-10-14 with steps 1–8 done. Miguel keeps `@ondestaanocas` for now; the rename with
  its own Project (step 9) moved to #27, so `brand.handle` and `affiliate.projects.instagram` (584711) stay.

## D20: Visual direction A "Caderno de Viagem" (2026-10-13, #11)
- **Decided by Miguel (2026-10-13): direction A, as is** (no mix, no further notes). Three
  directions were built as real pages (`uv run escapadinha design directions`, then open
  `output/directions/index.html`); B and C below are kept for the record.
- **Starting tokens for the design system (#12)**, from `design_directions/directions.py`:
  - Type: **Fraunces** (headlines and prices) + **Source Serif 4** (body and data), both SIL OFL 1.1,
    to be self-hosted (replaces D7's font choice).
  - Light: bg `#F5F0E6`, surface `#FFFDF8`, ink `#1E1B16`, muted `#5F574B`, accent (terracotta)
    `#A23E1C` with white text, rules `#D3C8B4`.
  - Dark: bg `#16140F`, surface `#201D17`, ink `#EEE7D8`, muted `#B3A994`, accent `#F0936B` with
    `#16140F` text, rules `#3D372C`. Every body-text pair passes WCAG AA (min 5.70:1).
  - Photo treatment: large captioned photos with credit; layout: masthead, column rules, drop caps.
- **Known weakness to solve in #12:** A is the slowest of the three to scan for a price, so price,
  dates and the "found on" line need a consistent, prominent component on cards, slides and pages.
- **A · Caderno de Viagem** (editorial magazine): Fraunces + Source Serif 4; paper, ink and a
  terracotta rust; large captioned photos, column rules, drop caps; literary tone where each price
  is a verified fact. Most aspirational and best for long itineraries, slowest to scan for a price.
- **B · Pôr do Sol** (warm sunset/coastal, closest to the partner's sketch): DM Serif Display + DM Sans;
  sand, coral, dusk purple and sea teal, night-blue in dark mode; rounded "postcard" photos with a warm
  wash, sun-over-mountain-and-sea mark, wave dividers; warm "tu" voice. Best fit with Instagram; risks
  looking generic if the gradient is overused.
- **C · Quadro de Partidas** (bold utilitarian deal board): Space Grotesk + JetBrains Mono; black,
  signal yellow (only behind black text), green for "below typical", red for "expired"; dense tables,
  tabular numbers, small black-and-white photos; terse factual copy. Fastest to read, furthest from
  the sketch.
- **Common rules:** all fonts are SIL Open Font License 1.1 (loaded from Google Fonts for the preview
  only; the chosen ones get self-hosted, which replaces D7). Palettes are defined once in Python and
  emitted as CSS tokens, so the contrast table on each page is computed from the shipped colours; every
  body-text pair passes WCAG AA (4.5:1) in light and dark, text on photos is measured on its scrim over a
  white pixel. Pages use real data only (DB opened read-only), mark expired promotions without a booking
  link and carry the disclosure. The mountain marks are provisional SVGs; the designer's logo is M6.

## D21: Database, archives, backups and run lock in Cloudflare R2 (2026-10-13, #4)
- **Why:** the pipeline moves to GitHub Actions (spec #1), which keeps nothing between runs. The
  SQLite file (≈1 MB after D18) is downloaded at the start of a run and uploaded at the end,
  which is simpler and cheaper than a hosted database and keeps plain SQL (D8).
- **Dependency: boto3** (runtime) + **moto** (tests). Rejected: httpx + hand-written SigV4. It
  would be ~150 lines of signing, XML listing/pagination and error mapping we'd own, and the
  contract tests would run against a fake S3 we wrote ourselves; moto's S3 is independent and
  honours the conditional headers the lock depends on. boto3 is imported only when the R2 keys
  are set. Client settings follow Cloudflare's boto3 guidance: region `auto`, checksums only
  when required.
- **Selection:** `Context.object_store` is `S3ObjectStore` when all four `R2_*` keys are in
  `.env`, else `LocalObjectStore(data/objects)`. No keys = exactly the previous behaviour.
- **Lock (`locks/run`, `{owner, expires_at}`):** acquire with `PUT If-None-Match: *` (one
  winner); an expired lock is taken over with `PUT If-Match: <etag read>` (one winner among
  racers); release only while the object still names us, with `DELETE If-Match` (plain DELETE
  where that is not implemented). TTL 60 min, well above a run; the Actions job timeout must
  stay below it. A held lock makes `run` exit 0 with a message and touch nothing (the next
  scheduled run will do the work).
- **Database objects:** `db/escapadinha.db` (SQLite backup API copy, `quick_check` before every
  upload and install) and `db/escapadinha.json` (`generation`, sha256, `pushed_at`, `pushed_by`,
  last run id), written in that order. A local `data/escapadinha.db.sync.json` holds the
  generation and file hash of the last pull/push: that is how `store push` knows the bucket moved
  on (refuse unless `--force`) and `store pull` knows there are unpushed local changes (refuse
  unless `--force`, which keeps a `.local-<time>` copy). Rejected: object ETags (not part of the
  `ObjectStore` interface; the local store has none) and a schema change (other tickets own it).
- **Run:** lock → pull → backup → steps → push → unlock. Push also happens when a step fails
  (collected data and its archives are already real). A run never blocks on a local conflict:
  local changes on the current generation are fast-forwarded, on an older one set aside as
  `.local-<time>`. `store push` takes the same lock, so it cannot interleave with a run.
- **Backups:** `backups/<Lisbon date>/escapadinha.db` = the database before that day's first run,
  so a bad run can be undone. Expiry is a bucket lifecycle rule (prefix `backups/`, 30 days),
  set by Miguel in the dashboard; the code never deletes backups. `store restore <date>` +
  `store push` puts one live.
- **Not synced yet** (local files the website build reads): `data/site_paths.json`,
  `data/site_links.json`, `assets/photos/`, `output/`. The Actions ticket must move or rebuild
  them before CI builds the site.
- **Set up 2026-10-13 with Miguel:** R2 subscription on the Free allowance (card on file, budget
  alert at 1 USD by email), bucket **`pontonomada`** (private, automatic location = Western Europe,
  Standard class), lifecycle rule `backups-30-dias` (prefix `backups/`, delete after 30 days),
  Account API token `pontonomada-pipeline` (Object Read & Write on that bucket only, no expiry).
  `store check` passed every line on the real bucket (both conditional-write lock checks), then
  `store push` (generation 1), `store upload-archives` (runs 1–16) and a real `run` (run #17:
  30 requests, 422 offers, 8 new; daily backup written; generation 2 pushed; lock free).

## D22: Design system, self-hosted fonts, provisional logo, restyled slides (2026-10-13, #12)
- **What:** direction A written down as `docs/design/design-system.md` (type, colour, spacing, radii,
  shadows, components, photo treatment, tone of voice) with machine-readable `docs/design/tokens.json`
  for Tailwind (M3). Values live in `renderer/tokens.py` (base palette imported from `CADERNO`); the JSON
  is generated from it and a test fails if it is stale or any text pair drops below WCAG AA.
- **States added:** `success` (below the typical low), `warning` (remote airport, warming up) and
  `expired`, each with a tint, in light and dark. Lowest ratio in the system: 5.43:1. State is never
  colour alone (always a word: "abaixo do habitual", "longe do centro", "Expirada").
- **D20's weakness (slow to scan for a price)** is answered by one price block used everywhere: route,
  price (largest element, ink, lining tabular figures), discount tag, dates and "encontrado a", always
  together and in that order. On slides it sits on a paper card, never on the photo.
- **Photos:** text on photos only on a warm-ink scrim (`#16140F`) with eased stops, ≥ 0.70 under any text
  (6.69:1 over a white pixel). Checked by rendering the cover and CTA over every cached photo.
- **Fonts (replaces D7):** Fraunces and Source Serif 4 (SIL OFL 1.1, no Reserved Font Name) from the
  google/fonts repository, subset to Latin and converted to variable WOFF2 (~600 KB for 4 files, roman +
  italic), committed in `assets/fonts/` with their `OFL-*.txt`. Fraunces is pinned to `SOFT 0`/`WONK 0`
  (the Google Fonts default cut). The slides inline them as data URIs, so rendering stays offline (D6).
  `.gitignore` still ignores `assets/fonts/*.ttf` so no large source TTFs get committed.
- **Logo:** `assets/logo-light.svg` / `logo-dark.svg`, a line mountain with a terracotta sun plus the
  wordmark in Fraunces Italic outlined to paths (renders without the font). Replaces `assets/logo.svg`
  (the website copies the light variant as `/logo.svg`). Provisional until the designer's logo (M6).
- **Slides:** cover = photo + top scrim + paper card with the price block; slide 2 = paper "ficha" with
  a captioned photo band, rows, found vs checked (Lisbon time); slide 3 = dark CTA, photo fading into
  ink, disclosure notice. Guides follow the same pattern (photo cover with card, paper tip pages, dark
  CTA). All existing rules are unchanged (disclosure, found_date vs fetched_at, arrival airport).
- **Reviewed by Miguel (2026-10-13):** "Gosto do design por enquanto": slides and provisional
  logo approved for now; the designer's logo is still M6.

## D23: Route discovery from the provider's data, curated long-haul list, dormancy (2026-10-13, #5)
- **Sources (all Travelpayouts, no scraping, D13):**
  - Static catalogue `data/routes.json` (public): airline routes with `transfers`. Rows with
    `transfers: 0` from LIS, OPO, FAO, FNC, PDL, TER; arrival airports → city codes via
    `data/airports.json`; names from `data/pt/cities.json` (`name`, Portuguese; `name_translations.en`
    when it's missing). `countries.json` has no region, so Europe/North Africa is a country-code set
    in `discovery.py`.
  - **The static catalogue is years out of date**: it still has Transaero (ceased 2015), Lisbon-Moscow
    and Lisbon-Kyiv, and only 52 routes from Porto. So two supplements with the token, as the spec
    asked for the first: `v1/city-directions` (popular directions, ~30 per origin; only those whose
    cheapest fare was nonstop count) and `v3/prices_for_dates` with an origin and no destination,
    `direct=true`, one call per departure month (nonstop fares found recently: 91 destinations from
    Porto). Only destinations are taken from them; their prices are never stored (the collector stores
    prices, per route). A failing supplement is reported and skipped; a failing catalogue aborts
    before anything changes.
  - Kind: Portugal → `domestic` (this includes the few mainland routes such as LIS-OPO), Europe and
    North Africa (MA DZ TN LY EG) → `europe`; anything else only if it's on the long-haul list for
    that origin. Same-city pairs are dropped. Existing routes keep their name, kind and rules;
    discovery only fills `destination_airports` and `city_en`.
  - `routes.city_names` fixes catalogue names (it mixes airport names, Brazilian spellings and errors:
    Hamburg is "Finkenwerder", Algiers "Argélia", Malta "Luqa"). Exclusions `MOW LED IEV MSQ`: airspace
    closed since 2022, still in the old catalogue.
- **Long-haul list (20, from LIS and OPO, rules from the kind: ≤ 1 stop each way, 7–21 nights):**
  Nova Iorque, Boston, Miami, Washington, Toronto, Montreal (TAP/Air Transat/Azores Airlines nonstops
  from Lisbon; NYC and Toronto from Porto too), Rio de Janeiro, São Paulo, Salvador, Recife, Fortaleza
  (TAP's Brazil network), Ilha do Sal and Boa Vista (Cabo Verde; nonstop, holiday islands), Cancún,
  Punta Cana (one stop via Madrid/Paris), Dubai (Emirates nonstop), Maldivas, Banguecoque (one stop via
  the Gulf), Tóquio (one stop; the spec's "Japão desde 564 €" example), Cidade do Cabo (one stop).
  Checked on 2026-10-13 against cached fares: every one has fares from Lisbon with ≤ 1 stop except
  Banguecoque and Maldivas (cache only had 2-stop fares that day; one-stop service exists via DXB/DOH).
  From Porto most need a stop in Lisbon and the cache is thin (no fares yet for 10 of the 20): those
  routes will go dormant and be re-probed monthly. Left out: Natal, Belo Horizonte, Porto Alegre,
  Brasília (thin demand), Luanda/Maputo/Bissau/São Tomé (diaspora and business travel more than deals),
  Chicago/San Francisco (no fares in the cache). Ponta Delgada's nonstops to Boston and Toronto are
  not listed: add `PDL` to those entries' `origins` if wanted.
- **Dormancy:** after every collection that didn't fail outright, an active route with no price seen
  for 30 days (newest `last_seen_at`, or `discovered_at` if never observed) becomes `dormant` and is
  not collected. A discovery that finds it again reactivates it, and the next collection is its probe:
  with prices it stays, without it sleeps again (one probe per month = 3 requests, instead of 30 days
  of requests). Curated long-haul routes count as found every time. `last_observed_at` now follows
  `last_seen_at`, not the first sighting: with dedup (D18) an offer that keeps coming back would
  otherwise look unobserved. Nothing is deleted; excluded routes are left alone.
- **Schedule:** `routes discover` on demand; `run` discovers when the last discovery (kept in a new
  `meta` key/value table) is 30+ days old. A discovery failure never stops the collection.
- **Photos:** every destination of an active route gets a Pixabay photo (query: `photos.queries`,
  else the English catalogue name, stored in `routes.city_en`), at most 40 per discovery/run (2 calls
  each against Pixabay's 100/min).
- **Schema v8:** `routes.city_en`, table `meta`. Upgrades tested from v5 and v7.
- **Real run, 2026-10-13 (copy of the real DB):** found LIS 113, OPO 107, FAO 67, FNC 50, PDL 17,
  TER 8 = 362 (2 excluded) → **360 active routes**: LIS 111 (91 + 20 long-haul), OPO 107 (87 + 20),
  FAO 67, FNC 50, PDL 17, TER 8; by kind 277 europe, 43 domestic, 40 long-haul; 155 destinations.
  Sources: 284 routes had a recent nonstop fare, 57 only the static catalogue, 19 only the curated list. One collection right
  after: 1080 requests in 5 min 40 s, no 429, prices for **230 of 360** routes (most of the rest are
  summer-only UK/German routes from Faro and Madeira, Azores inter-island routes and Porto's long-haul).
  So the spec's ~250–300 is where the active count should settle once the first 30-day window has
  put the routes without prices to sleep; the count before that is 360.
- **Budget:** one request per active route and month: 1080 per run now, ~800 once dormancy settles,
  latency-bound at ~190/min (client cap 550/min, API limit 600/min). **For GitHub Actions (#4 and
  later):** ~6 min × 12 runs/day ≈ 2200 min/month, above the 2000 free minutes of a private repo
  (public repos are unmetered). Options when moving: concurrent requests under the same cap,
  fewer months for dormant-prone routes, or a public repo.

- **Label (Miguel, 2026-10-13):** the `domestic` kind is shown as **"Portugal"** (islands, inter-island
  and mainland routes such as Lisboa → Porto), replacing "Ilhas". Merged into the live pipeline the
  same day: the scheduled run discovers ~360 routes and collects ~1080 requests per run.
- **Photo search fix (2026-10-13, after the first real discovery):** the first automatic picks
  were often wrong (Brussels → sprouts, Bristol → Maine, Montreal → a brick wall, Cape Town → a
  bird). The search now tries Pixabay categories travel → places → buildings → any and keeps
  photos tagged with the city's English name, falling back to the travel results; overrides in
  `photos.queries` for the remaining bad ones; `max_per_run` 20 (up to 5 calls per destination).
  Pixabay's tags are keyword-stuffed and some cities have few photos (Algiers), so a deal's photo
  is still checked by Miguel on the slides before posting (`photos fetch --dest X --force --pick N`).

## D24: Two publication tiers, partner links per low price, traceability test (2026-10-13, #6)
- **Why:** at ~360 routes (D23) one 30 % threshold gives either an empty site or a flooded review
  queue. The spec (#1, stories 17–22) splits a run's output in two, both measured against the
  same typical low (D3, unchanged).
- **Low prices** (`detector.low_prices`): fresh offers within the route's rules at least
  `low_threshold` (0.15) below a **mature** typical low (≥ `min_baseline_days`; since D40, 7 daily
  lows from days with two departure dates, and promotion candidates need 10 spanning 9), one per trip
  dates (the cheapest), biggest discount first. No price-cap path: without a typical low there is
  nothing to be "low" against, and they go out without review. Offers that already are deals still
  count (a low price is not a post).
- **Promotion candidates** (`detector.detect_route`, unchanged rules plus one): ≥ `threshold`
  (0.30) **and** ≥ `min_saving_eur` (15 €) below the typical low; one per route per run, 7-day
  dedupe, never an offer that already is a deal. The euro floor keeps cheap routes out of the
  queue (40 € typical low: 26 € is −35 % but 14 €). The price-cap path is unchanged and has no
  euro floor (there is no typical low to save against). `low_threshold ≤ threshold` is enforced.
- **One call, two outputs:** `detector.detect` returns `Detection(low_prices, candidates)` from one
  set of month baselines; `taken` (deal observation ids) only filters candidates. `run_detect`
  creates deals from candidates only and reports the low-price count per route.
- **No low-price table:** low prices are a pure function of the latest completed run
  (`observations_seen_since`, D18) and the stored history, so the site recomputes them at build
  time (`pipeline.route_low_prices`). The JSON export for the Astro site is #10.
- **Route pages** list the latest run's low prices (at most `site.low_prices_per_route` = 5,
  biggest discounts, shown by departure date) with price, −% vs. habitual, dates, airline, arrival
  airport, "encontrado a" (`found_date`) and "visto por nós a" (first `fetched_at`, Lisbon time;
  stable across runs, unlike `last_seen_at`, so an unchanged list doesn't force a deploy), and the
  affiliate disclosure next to the buttons. A live promotion's own offer is not repeated. Home and
  promotion pages are unchanged.
- **Partner links, volume:** the price must come from the same place as the link (D13), so each low
  price links its own offer (its `deep_link`, moved to aviasales.pt), converted by
  `PartnerLinksClient` for the website Project (`sub_id=site-low-<observation id>`); never a
  hand-built `marker=` URL. Estimate: 230 routes with prices × ≤ 5 = ≤ 1150 links when the
  baselines mature, turning over within ~3 days (freshness window), so tens of new ones per
  2-hourly run. Rejected: one link per route (a dateless search URL wouldn't show the price we
  print) and a new link per low price on every build (~115 requests in one burst, above the API's
  100 requests/min, and ~1150 throwaway short links every 2 hours). Chosen: create once per (observation, Project) and **store it in the
  database** (`partner_links`, schema v9), because the database is synced to R2 and a CI runner
  (#7) keeps no files (D21: `data/site_links.json` isn't synced yet). Each build converts at most
  `site.max_new_links_per_build` (300 = 30 requests, ≤ 900 enforced so one build stays under the
  per-minute limit), biggest discounts first; the rest and failures wait for the next build and are
  shown meanwhile without a button (on the Astro site with the note "Ligação de reserva
  disponível em breve.", `cta.NO_LINK_NOTE`, next to the found-on date). Since D27 the cap is one budget per collection run, shared by
  the site data export and the site build (meta `site.link_budget`, see D27). Rows older than 30 days are pruned (their offers left the
  freshness window long before). On a copy of the real database (2026-10-13, baselines still
  warming up after discovery): 7 low prices on 360 route pages, 0 promotion candidates.
- **Traceability test (D2 enforced, story 22):** price elements carry `data-obs` / `data-deal` /
  `data-route`. `tests/test_traceability.py` (normal run, no browser) builds a database with live,
  expired and new promotions, low prices (including a decimal one and a 14 € small-fare low) and an
  even-count typical low (100,50 €), renders the site and every deal and guide caption, and fails on
  any price string that is not a referenced observation's price, a referenced deal's stored
  `baseline_median` or recheck price (only if a stored observation of that trip has it), or a typical
  low recomputed from the referenced route's observations. It also proves the checker catches a
  fabricated price and a real price the page doesn't reference. Slides (PNG) aren't checked; they
  render the same `DealView` as the caption.
- **Schema v9:** table `partner_links (observation_id, project_id, partner_url, error, created_at)`.
  Upgrades tested from v5 and v7.
- **Actions budget, Miguel's choice a) (2026-10-13):** collection runs `collector.workers` (8)
  requests at a time under the same thread-safe 550/min limiter; responses are still stored and
  archived in request order on one thread. ~1080 requests then take ~2 min (limit-bound) instead
  of ~6, so 12 runs/day fit the 2000 free Actions minutes of a private repo (#7).

## D25: GitHub Actions pipeline, fast and full path, nothing kept on the runner (2026-10-13, #7)
- **Workflow** `.github/workflows/pipeline.yml`: cron `17 */2 * * *` (UTC; :17 avoids the
  top-of-hour queue), `workflow_dispatch` (input `full`) and `repository_dispatch` (types
  `review-decision`, `full-run`; both force the full path, for the review Function later).
  `concurrency: pipeline` with `cancel-in-progress: false` (a queued run waits; the R2 lock is
  the second guard, against the PC). `timeout-minutes: 45` < the lock's 60 (D21). Secrets are
  Actions secrets exposed as environment variables, which `config.Secrets` reads without a
  `.env`; nothing echoes them (a test checks the file). uv via setup-uv with its cache; Node 22
  for `npx wrangler` (D15). Supersedes D9 once the PC task is unregistered.
- **Fast or full path, decided in Python** (`run_path.py`, testable, not YAML). After detect,
  `decide` compares a fingerprint with the one stored in `meta` (`run.full_path_fingerprint`) at
  the end of the last successful full path. Components, each hashed: promotions (every deal's
  id, status, has-link), the low prices the route pages list (same selection as the site:
  `pipeline.shown_low_prices`), routes (key, status, pt name), the Lisbon date, and the code
  (package files, config.yaml, content/; line endings normalised so the PC and the runner
  agree). Any change, a missing fingerprint or `--full` → full path (render new deals → site
  build → deploy when the content hash changed); the log prints `Path: fast|full (reason)`. A
  failed full path stores nothing, so the next run retries it. Review decisions made elsewhere
  (#8) change deal statuses and so trigger it without #7 knowing about events. Rejected:
  "new observations this run" (true almost every run), and comparing the built site's content
  hash (needs the build, i.e. the cost we are avoiding). The date component means one full path
  a day even when nothing else changed: route pages show typical lows, which move daily, and
  are otherwise left out of the fingerprint on purpose (they would make every run full).
- **Run status:** `run` prints `Run <status> in <duration>` and, when `GITHUB_STEP_SUMMARY` is
  set, writes status, duration, collection counts and the path decision to the run's summary.
  A failed request is listed and skipped (collector, unchanged, now tested through `run`); only
  a collection where every request failed exits 1. The database is pushed either way (D21).
  Route upkeep before the collection (discovery when due, else missing photos) never fails the
  run: API errors and object-store errors (`s3.STORE_ERRORS`, e.g. an R2 hiccup while mirroring
  a new photo) are printed and the collection goes on; the photo is fetched again next run.
- **Chromium only when needed:** the workflow sets `ESCAPADINHA_INSTALL_BROWSER=1`;
  `renderer.ensure_browser` runs `playwright install --with-deps chromium` the first time a
  `SlideRenderer` opens, i.e. only when there is a deal or guide to render. The download is
  cached (`~/.cache/ms-playwright`, keyed on `uv.lock`); the system libraries come from apt
  each time it runs. The fast path never touches either.
- **What a fresh runner lacks (D21's list), simplest correct home for each:**
  - `data/site_paths.json` (redirect history; losing it would drop 301s) → database, `meta`
    `site.paths`. `data/site_links.json` (website partner links; losing it would create
    duplicates) → `meta` `site.links`. `data/site_deploy.json` (last deployed content hash,
    not in D21's list; losing it would redeploy every full path) → `meta` `site.deployed`.
    They are small JSON, belong with the database's state, and are then backed up and
    restored with it. The old files are still read and merged in (paths: union; links: entries
    the database lacks; deploy: only when the database has none), so the PC's history reaches
    the database on its next build without a manual step; the files are no longer written.
  - `assets/photos/` (Pixabay cache, ~155 JPEGs) and the rendered folders under `output/` that
    the site and the review page read → the object store under `photos/` and `output/`, same
    relative paths, through `storage.mirror.Mirror` (`ctx.object_store`, so R2 or nothing:
    without R2 keys it only looks at the local folder). Uploaded when made (photo fetched, deal
    or guide rendered), downloaded on first use (`pipeline.deal_folder` resolves a stored
    `output_path` written on any OS by its last two parts; `guide_folder` takes the latest
    stored date; `_photo`). Only the files a step reads are fetched, each at most once per
    machine (`deal_folder(ctx, deal, files=pipeline.SLIDES)`: the site build gets the slide
    PNGs, never `caption.txt`/`meta.json`; a local copy is never fetched again), and the site
    data export only lists slide names (`deal_slide_names`, one LIST per public deal, no
    download); a test counts the GETs of a runner's export + build. `mirror_local_files` (run
    on every full path) uploads what the PC
    made before D25 and the bucket lacks: one LIST per prefix, nothing on a runner. Rejected:
    re-rendering slides on the runner (they must stay what Miguel reviewed and posted) and
    photos as database blobs (~50 MB in a file pulled every 2 hours).
  - A test builds the site on the PC, pushes, pulls into an empty checkout and builds again:
    the two sites have the same content hash (redirects, cached links, slides, guide images),
    no partner link is created twice and the deploy is skipped as unchanged.
- **Not synced, on purpose:** `logs/`, `site/` (rebuilt), the `EXPIRADO.txt` note (written only
  where a rendered folder exists locally; the review snapshot of #8 covers the runner case).
- **PC fallback:** the Windows task keeps running until a clean week on Actions; both take the
  R2 lock, so they never overlap. Retire it with `scripts\register-task.ps1 -Unregister`
  (= `Unregister-ScheduledTask -TaskName "Escapadinha collect" -Confirm:$false`).
- **Miguel's steps:** add the nine Actions secrets; run the workflow once by hand
  (`gh workflow run pipeline.yml -f full=true`) and check its summary and *Usage* (fast path
  target ≤ 2 min); after a clean week, unregister the PC task.
- **Note (2026-10-15, D41):** the cron above turned out best effort (9 scheduled runs came
  4.4–6.8 h apart); the 2-hourly runs had come from the PC task, retired that day. `pipeline.yml`
  no longer has a `schedule`: a Cloudflare Worker dispatches it every 2 h, and a separate
  `pipeline-fallback.yml` (GitHub's cron, every 6 h) dispatches it only when no run started for
  3 h. The minutes budget above (~720/month) assumed ~2 billed minutes a run; jobs bill whole
  minutes and a run bills ~3.2, see D41.

## D26: Review decisions as events, applied by the pipeline; review snapshot (2026-10-13, #8)
- **Why:** with the database in R2 (D21) a decision written into a local copy is lost or collides
  with the next run's push, and the review Function (#9) can't open SQLite at all. Decisions
  therefore become an append-only log in the object store, and only the pipeline, holding the
  run lock, turns them into statuses (story 25).
- **Event** (`contract/review/v1/event.schema.json`): one JSON object per decision at
  `review/events/pending/<YYYYMMDDTHHMMSSZ>-<id>.json` with `version` 1, `id` (UUID v4), `type`
  (`approve` | `reject` | `published`), `deal_id`, `created_at` (UTC, `Z`), `actor`
  (`cli:<user>@<host>`, `review-page:<user>@<host>`, or the Access e-mail from the Function),
  `note`, `post_url` (published only) and `live_check` (`{valid, price_eur, reason, checked_at}`,
  required and valid on approve, null otherwise). Every key is always present. `created_at`
  becomes `reviewed_at` / `published_at`. Events are never edited: a new decision is a new event.
- **Applier** (`pipeline.apply_review_events` → `review_events.apply_pending`), first step of
  every `run`: pending events oldest first; each is re-checked with `review.check_decision`
  against the deal's status *now* (same rules as before writing: transition table, affiliate link
  for approve, `https?://` post URL) and approve also needs `live_check.valid`. The outcome
  (`applied` | `refused` with the pt-PT reason) and the status change are written in **one
  transaction** together with meta `review_event:<id>`. Unparseable objects are `malformed`. Every
  event ends in `review/events/archive/<YYYY-MM of creation>/<same name>` as
  `{event, outcome, reason, settled_at, status_before, status_after, ...}`. Nothing in here raises
  for a bad event or a store error during archiving.
- **Idempotency:** the database is the only judge of "already applied": an id with a meta
  outcome is never applied again, whatever the store holds (a re-delivered copy, a pending object
  whose delete failed after the archive put). Archive put comes before pending delete, and the
  archive key is a function of the pending name, so retrying writes the same object. **With R2 the
  database is only durable after the run pushes it**, so an event applied by run N stays pending;
  run N+1, starting from the pushed database, finds the outcome and only archives it. If run N
  died before pushing, run N+1 starts from the older database and simply applies it again.
  Without R2 the database is durable on commit and events are archived at once.
- **Where the live check happens:** in the writer, right before an approve event is written (CLI
  and local page: `pipeline.price_now`; Function: its own request with the query the snapshot
  gives it). It is a gate only: it stores no observations and changes no status, because the
  Function has no database and both paths must behave the same. A moved price refuses the
  approval with the reason and writes nothing; the next collection's recheck (every 2 h, same
  rule) expires the deal. The applier doesn't call the provider: it re-checks the status, so a
  deal that expired between the check and the run is refused, and approved deals keep being
  rechecked by every run, so "never publish expired" holds. `deal check` (and the page's
  *Verificar preço agora*) without R2 keys keeps storing a `live_check` run and expiring on a
  moved price (a recheck, pipeline-owned, on the only database). With R2 keys it is report-only
  (`price_now`: no run stored, no status change): its write would land on a local copy that the
  next pull sets aside, so the run's recheck (same rule, every 2 h) expires the deal instead.
  This was the last status write outside the applier and the run.
- **Approvals expire after 24 h (Miguel, 2026-10-13):** the applier refuses an `approve` event
  whose `live_check.checked_at` (else `created_at`) is older than `review.approve_max_age_hours`
  (config, default 24) at apply time, reason "Aprovação com mais de 24 h: verifica o preço outra
  vez."; the reviewer approves again with a fresh check. Normally a run applies an event within
  2 h (D25); this bounds the stale-approval case (runs failing or paused, an event written from
  an old snapshot). `reject` and `published` have no age limit. The limit is passed into
  `review_events.apply_pending` (`approve_max_age`), never read from a global, and the snapshot
  carries it (`review_rules.approve_max_age_hours`) so the Function can warn before then.
- **CLI and local page:** `deal approve/reject/published` and the page's buttons pre-check the
  same rules (and refuse while the deal has a pending decision), write the event and print the
  pending list. Without R2 keys nothing else owns the database, so they apply pending events at
  once (same experience as v1). With R2 keys they leave the event for the next run (or the
  Function's dispatch) and say so; the local database copy is not touched. They pre-check on
  that local copy, so they refuse (ReviewError) while `sync` shows the bucket's generation newer
  than the one the copy came from (or the copy was never synced): "corre `escapadinha store pull`
  primeiro" (`pipeline.ensure_current_copy`, one GET of the metadata). A deal missing from the
  copy is a `review.UnknownDeal` ("O deal N não existe nesta base de dados.", 404 on the page),
  never a bare `KeyError`.
- **Contract:** only `review_events` writes approved/rejected/published (`db.settle_review_event`);
  `db.record_review` is test setup only, and a test fails if any other module calls either.
  Render (new → rendered) and rechecks (→ expired) stay with the pipeline.
- **Snapshot** (`contract/review/v1/snapshot.schema.json`), `review/snapshot.json`, last step of
  every run (fast or full): `queue` (new/rendered), `approved`, `published` and `closed` (latest 20
  each), every deal with price (number and pt-PT text), dates, nights, airline, arrival airport,
  discount, typical low, found/fetched/detected times, affiliate link, caption, `whatsapp_text`
  (null until generated; filled since D32), `page_url`, `slides` and `live_check` (last recheck, expired reason, the
  exact provider `query` and the route `rules` + freshness window, so the Function's check is the
  pipeline's rule); plus `pending_events` (not yet in this database) and `recent_outcomes`.
- **Slides:** "slide URLs on the public site" only exist for deals the site shows
  (`<base_url>/img/promos/<id>/slide_NN.webp`, approved/published/expired-after-approval). A queue
  item is not public, so every deal still open for review also gets WebP copies in the store at
  `review/slides/<id>/slide_NN.webp` (uploaded once, deleted when the deal leaves review); the
  Function serves those behind Access (WebP, lighter on a phone than the PNGs under `output/`, D25).
  On a runner, slide names come from the `output/` listing and a deal folder is only downloaded to
  make missing copies. Rejected: publishing queue slides on the public site.
- **Run order (with D25):** `apply_review_events` → collect … → fast or full path →
  `export_review_snapshot`, the snapshot on both paths and also when a later step fails (a
  collection where every request failed exits 1 after exporting it, so decisions the applier
  just settled are visible; a snapshot error then never hides the run's own error). A status the applier changes is part of
  D25's fingerprint, so an applied approval takes the full path without the applier knowing.
- **No schema change:** outcomes live in `meta` (one row per decision, a few a day).
- **Shared with the site (D27):** "public" (`website.is_public`), page slugs (`promo_slug`) and
  the image folder (`promo_image_dir`) are the site's own helpers, so the snapshot's `page_url` and
  slide URLs are the paths `site build` and the site data export write.

## D27: Website data contract v1: JSON Schema, export, committed fixtures (2026-10-13, #10)
- **What:** the Astro site (M3) is built from JSON only (spec #1, "Website"). Schemas (draft
  2020-12) in `contract/site/v1/`: `meta`, `labels`, `origins`, `routes`, `destinations`,
  `promotions`, `low-prices` (one file per origin) plus shared `defs` (`eur`, `offer`, `rules`,
  dates, ...). `site_data.export_site_data` writes them (`escapadinha export site-data`, default
  `site.data_dir` = `output/site-data/v1`, `web/src/data` once the web package exists); `run`
  calls it in the full path (D25) right before `site build`, on the local disk (not R2). The
  full-path fingerprint (`run_path`) covers what the Jinja site shows plus the day, so the
  export's extra rows (every low price, not only the 5 per route page) refresh at least daily;
  once the Astro site is the live one (#13) the fingerprint should cover the export itself
  (e.g. a hash of its files): done at the cutover, D35. Tests validate the export with
  `jsonschema` against the committed schemas. **Versioning:** the directory is the major version;
  additive changes (new optional data, new files) stay in v1, anything that breaks a consumer is v2.
- **Same rules as the Jinja site, not a second implementation:** routes from `routes.all_routes`,
  typical lows from `detector.month_baselines`, low prices from `detector.low_prices` over the
  latest run, public deals from `website.public_deal_rows` (shared with `SiteBuilder`, as are
  `is_public`, `route_slug`, `promo_slug`, `promo_image_dir` and `deal_image_paths`; the review
  snapshot of D26 uses the same ones), so page paths and image URLs are the ones the current site
  serves (a test builds both and checks the files exist). The Jinja site is unchanged. Slide
  names come from `pipeline.deal_slide_names` (the local folder, else the `output/` listing of
  D25, nothing downloaded), so a runner without `output/` exports the same image paths as the
  PC (tested).
- **Promotions: live and recently expired** (spec #10): every live promotion, and expired ones
  for `site.expired_promotions_days` (30) after they expired (their last check, the recheck that
  expired them; else detection), so the file doesn't grow forever. Route counts and
  `meta.counts` follow the same window. The Jinja site's expired pages are unchanged (they stay,
  `noindex`, so shared links never break); the Astro site decides what an old link shows (#13).
- **Raw values, few display strings:** ISO dates, UTC timestamps (`Z`), euros as numbers, codes.
  pt-PT number/date formatting moves to the site; what it cannot derive comes from `i18n_pt.py`
  in `labels.json` (airline and airport names, remote airports, kind and status labels, month and
  weekday names, both disclosures). `found_date` and `fetched_at` stay separate fields (D10); the
  arrival airport is always present (D11).
- **Plain average:** `routes[].months[].average` = mean of the same daily lows as the typical low
  (`Baseline.mean`), context only (story 19). Typical low and average are `null` while a month has
  fewer than `min_baseline_days` days (counted as D40 says), so the site says "ainda sem dados"
  instead of a number.
  Route `cheapest` = cheapest offer within the rules in the latest run, found within the freshness
  window (origin pages' "a partir de"). A route-page price calendar was left out of v1 (see open
  questions); it can be added as an optional field or file.
- **Traceability (D2) on the JSON:** every price is an `eur` field next to what it traces to:
  an offer's `obs`, a month's route key (recomputed by the test from stored observations), a
  promotion's deal (`typical_low` = `deals.baseline_median`; the expiry's recheck price comes with
  the id of the stored observation of that trip that has it, or is null). `test_site_data.py`
  checks every price that way, runs the page checker on expiry reasons, and walks the schemas:
  a new `eur`/`offer` field fails until the checker knows how to trace it. The web package will
  render `data-obs` / `data-route` / `data-deal` from these ids.
- **Links:** only from the partner links API. The export calls `pipeline.low_price_links` (for
  every exported low price, not just the 5 per route page) and `pipeline.website_links`, which
  create missing links once and store them; `site build` right after finds them stored.
  **One link budget per collection run** (D24's `site.max_new_links_per_build`): the export
  spends first (biggest discounts first), the build gets what is left (`pipeline.link_budget`;
  meta `site.link_budget` = `{run, used}`, reset when a new collection run completes), so a run
  sends at most 90 requests even at the 900 maximum, under the API's 100/min. Failed requests
  count against it and are retried next run. `--no-new-links` (and the fixtures) only read
  stored links (`create=False`).
- **Per-origin low-price files (size budget):** rows are arrays in a fixed column order
  (`obs, dest, price, dep, ret, found, fetched, airline, stops, airport, typical, link`), one row
  per line, sorted by departure, return, destination, price, id; sorted keys, no other whitespace:
  deterministic, stable diffs, gzip-friendly. ~135 bytes per row measured; the test enforces ≤ 160
  on average and the cap `site.max_low_prices_per_origin` (1500, biggest discounts kept,
  `truncated` says how many were cut), i.e. at most ~240 KB raw per origin, about 4× smaller
  gzipped. Every origin with routes gets a file (possibly empty), loaded lazily by the explorer.
  A live promotion's own offer can also be a low-price row (the explorer can dedupe by `obs`).
- **Fixtures** (`contract/site/v1/fixtures/`, committed, `escapadinha export fixtures --db
  data/escapadinha.db`): the real database is opened with `mode=ro` and copied into memory
  (migrated there, never in the file); the windows are those of the latest run (`now` = its
  finish time), so regenerating the same database gives the same files. ~10 routes: the three
  busiest origins' best routes (promotions, low prices, prices), plus a long-haul, a domestic, a
  dormant route and one without a typical low when the data has them. Anonymous: booking links
  become `https://example.com/parceiro/<sub_id>` (every live promotion and low price gets one, to
  show the tracked-link state), photographers' names and profile URLs a placeholder; no review
  notes, post URLs, deep links or secrets are exported at all. **Fixture-only statuses:** the
  real data had no approved deal yet (3 deals, all expired before review), so on the in-memory
  copy the newest deal is marked live and an expired one as approved before it expired; prices
  stay those deals' real observations. `meta.fixture: true` marks the set: never deploy it.
  Generated 2026-10-13 from run 18: 10 routes (LIS, OPO, FAO), 8 destinations, 1 live + 1 expired
  promotion, 6 low prices, ~19 KB in all.
- **Not in v1 (questions for #13–#15):** destination photos and promotion images are paths, not
  files: the web package must copy `assets/photos/` and the converted slides (today written by
  `site build` into `site/img/`) or the export must start writing them; a per-route calendar of
  cheapest prices per departure date (#14); destination "best months" are derivable from
  `routes.json`; the explorer only sees low prices (none until baselines mature, D24).

## D28: Astro site scaffold on the data contract (2026-10-13, #13)
- **What:** a separate npm package in `web/` (own `package.json` + committed lockfile, exact
  versions, Node 22 in CI) builds the M3 site from the contract JSON only (D27): home page and
  promotion pages, live and expired. The Jinja site stays the live one until the cutover (#23, D35);
  `config.yaml` `site.data_dir` is unchanged until then. `web/functions/` is reserved for the
  review Function (#9).
- **Astro 7.3.5, static output** (`trailingSlash: always`, directory format, so paths are the
  current site's `/promos/<id>-<origem>-<destino>/`; CSS inlined into each page). 7.x was the
  current major (7.3.8 latest on 2026-10-13); 7.3.5 was picked as the newest release older than
  two weeks. Astro telemetry is disabled in CI (`ASTRO_TELEMETRY_DISABLED`).
- **Tailwind 4.3.3** via `@tailwindcss/vite`, CSS-first. The design tokens are not copied by hand:
  `web/scripts/tokens.mjs` generates `src/styles/tokens.css` from `docs/design/tokens.json`: an
  `@theme` that resets Tailwind's colour, font, text-size, radius and shadow namespaces
  (`--color-*: initial`, …) so no framework default leaks through, then maps every token
  (`--color-accent: var(--pn-accent)`, `--text-price-xl` with its line height, tracking and
  weight, `--spacing-lg`, `--radius-sm`, `--shadow-focus`), plus the light/dark `--pn-*`
  palettes (`prefers-color-scheme` and `data-theme`), plus the dark palette under fixed
  `--pn-dark-*` names for surfaces that stay dark in both schemes (the `.photo-placeholder`
  gradient behind a slide or thumbnail, dark `rule` to `photo.scrim`). The same script writes
  `src/lib/tokens.ts` (`TOKENS`, the JSON as a dependency-free module) for code that can't use CSS
  variables: theme-color metas, the OG image, the logo's recolouring, the review page (D29). A
  vitest test fails while either file is stale; `tests/test_web_tokens.py` compares both value by
  value with `tokens.json`, so a change to `renderer/tokens.py` fails `uv run pytest` until
  `npm run tokens` is run. `web/test/colours.test.ts` fails on any raw hex / `rgb()` / `hsl()`
  colour in `web/src/` (templates, `global.css`, modules) outside those two generated files.
- **Fonts through Astro's Fonts API** (local provider, files from `assets/fonts/`): family and
  fallback stacks come from `tokens.json` in `astro.config.ts`; Astro adds metric-matched
  fallbacks (`size-adjust`), so swapping in the web font barely moves the page (CLS 0.13 → 0.015
  on the expired page). That match is against Georgia / Iowan, which Linux and Android don't have:
  on the PR runner the swap moved whole sections (CLS 0.19 on a destination hub, 0.26 on a ponte
  page). Since #14 the fonts use `font-display: optional`: the browser uses the web font only if it
  is there before first paint (from cache after the first page), otherwise the fallback for that
  page, so a font never moves the layout on any system (2026-10-14). No font preload and no italic on first paint: Lighthouse's simulated
  throttling counts fonts fetched before the first paint against it (FCP 3.0 s → 2.4 s), and the
  slides keep the italic voice. The logo is `assets/logo-light.svg` inlined with its ink and sun
  recoloured to `currentColor` / accent, so one file works on paper and in dark mode.
- **Input seam:** `SITE_DATA_DIR` (relative to `web/`, default `web/src/data`, git-ignored: the
  future export target) names the contract directory; `npm run build:fixtures` / tests / Lighthouse
  point it at `contract/site/v1/fixtures`. A Vite virtual module (`virtual:site-data`) loads
  every file named in `meta.json` and validates it with **ajv 8.20.0** (draft 2020-12, the
  committed schemas, `allErrors`) before any page renders; a mismatch or a missing directory
  stops the build with the file and field. A fixture build marks `<html data-fixture="true">` so
  the cutover's deploy step can refuse it. **Two builds, on purpose:** `npm run build:fixtures` is
  the build on a fresh checkout and in CI (and what `npm test` builds); plain `npm run build` is
  the build from real data and fails while `web/src/data` is empty (no `meta.json`), telling you
  to run `escapadinha export site-data --out web/src/data` (or to use the fixture build). The
  guard stays: a build that silently fell back to the fixtures could be deployed as the site.
  So #13's acceptance "`npm test` and `npm run build` green" reads as `npm test` and
  `npm run build:fixtures` green on a checkout, and `npm run build` green after an export.
- **Shared modules for #14+:** `src/lib/format.ts` (pt-PT: "49,50 €" with a no-break space,
  "sex, 6 nov", "6 a 9 de novembro", "12/10/2026 às 22:17" in Europe/Lisbon via `Intl` time zone
  data, month/weekday words equal to `labels.json`, tested; prices and discounts also come in
  parts, `eurParts` / `discountParts`, so a component styles the raised "€" or drops the minus
  sign without parsing a formatted string; every pt-PT string the review Function builds comes
  from here too), `src/lib/promotion.ts` (the
  promotion view, like `presentation.DealView`: remote arrival airport in the headline; it
  carries the traveller's found date and our `checked_at` ("verificado a": last recheck, else
  first fetch), the two times the page shows, and no field nobody renders),
  `src/lib/cta.ts` + `BookingCta.astro` (a button only when the price is live and the contract
  has a link, `rel="sponsored nofollow noopener"`, `labels.disclosure.site` next to it, never a
  hand-built link). The site uses the contract's **site** disclosure next to buttons (its
  documented place); `disclosure.post` stays for captions and CTA slides, which the promotion
  page shows as images.
- **Traceability (D2) in vitest:** `web/test/traceability.test.ts` walks every built page (text
  and attribute values, prices split over elements included) and requires each price to sit in or
  under the nearest `data-obs` / `data-deal` / `data-route` element whose contract amounts include
  it (observation price; deal offer, typical low, recheck price; route month typical low or
  average, cheapest). Element-level, stricter than the page-level Python checker. Pages with a
  price in `<title>`/descriptions put `data-deal` on `<head>`.
- **Expired promotions:** page kept at its URL, `<meta name="robots" content="noindex">`, no
  booking button, the recheck's reason in an expired notice that carries the recheck price's
  `data-obs`, the old price struck through. The home page lists them under "Expiradas
  recentemente" without links to the partner.
- **OG images:** a promotion page uses its rendered `images.og` (the pipeline's `og.jpg`); other
  pages a branded default `og-default.png` (1200×630) rendered at build time with sharp from the
  logo's outlined paths on paper, so no font is needed and the M6 logo swap updates it.
  Promotion slides and thumbnails are contract paths only; the cutover must bring the real files
  (D27 open question). So that Lighthouse measures pages with their images, a **fixture build
  only** (`meta.fixture`) draws stand-ins at those paths (`src/lib/fixture-images.ts`, two
  endpoints under `src/pages/img/promos/[id]/`: the `.photo-placeholder` gradient at the slide,
  thumbnail and OG sizes, generated with sharp, so no binary is committed); a build from real data
  gets no such route. The link test now checks `/img/promos/` too.
- **Lighthouse CI:** `.github/workflows/web.yml` on pull requests touching `web/`, `contract/`,
  the tokens, fonts or logo: `npm ci`, `npm run typecheck`, `npm test`, fixture build, then `@lhci/cli@0.15.1`
  (run with `npx`, not a dependency: its old transitive dependencies carry audit warnings)
  against the static build: mobile form factor, simulated throttling, 3 runs (median), on the
  home page, the live and the expired promotion; performance, accessibility and SEO must be
  ≥ 0.9. `is-crawlable` is skipped because the expired page is `noindex` on purpose (vitest
  asserts robots per page type instead). Reports go to an artifact, never to public storage.
  Local run 2026-10-13: 0.94 / 1 / 1 on all three pages (best practices 0.96: the missing images).
  Local runs 2026-10-14 with the fixture stand-in images: median 0.94 / 1 / 1, best practices 1 on
  all three. **Known flake, not fixed:** about one run in five on the live promotion page reports
  CLS 0.46 (performance 0.73–0.78), all of it on the slide strip, which sits below the fold on a
  phone. It happens with and without the images and with `snap-proximity` too, and a
  PerformanceObserver in a 412 px frame never sees it, so it looks like Lighthouse's emulation
  laying the page out at desktop width first (where the strip is the first column) rather than a
  visitor's shift. A 3-run median fails only if two runs flake (~10 %); re-run the job, and look
  again with real slides at the cutover (#23).
- **pt-PT lint:** `web/test/pt-lint.test.ts` scans `src/**/*.astro` and `src/**/*.ts` (comments
  skipped) for an explicit list of Brazilian words and spellings ("você", "celular", "equipe",
  "registro", "ônibus", …) and English UI leftovers ("Book now", "Buy", "Search", …, matched
  case-sensitively so code identifiers don't trip it), and checks `lang="pt-PT"` on every page.
- **Not yet (later tickets):** route, origin and destination pages, explorer, sitemap, JSON-LD,
  analytics beacon, `_redirects`/`_headers`, About/Privacy pages (the footer links none of them
  yet), deploy and the `run` integration (#14–#16, #23).

## D29: Review queue on Pages Functions behind Access (2026-10-14, #9)
- **What:** the review queue Miguel uses on his phone is a Cloudflare Pages Function in the web
  package (`web/functions/`, TypeScript) deployed with the site to the Pages project
  `ondestaanocas`, at **https://pontonomada.pt/review**. It reads the snapshot (D26), serves the
  queue slides, runs the live check, writes review events and fires one `repository_dispatch`
  per decision. It is a writer of pending events only: statuses still change only in the
  pipeline's applier (D26).
- **Routes**, all under `/review` so the one Access application covers them:
  `GET /review` (server-rendered page), `GET /review/slides/<id>/slide_NN.webp` (streams the WebP
  copy from `STORE`; only that key pattern), `POST /review/check` `{deal_id}` (live check, writes
  nothing), `POST /review/decision` `{type, deal_id, note?, post_url?}`. Two route files
  (`review/index.ts`, `review/[[path]].ts`) call the same `serve`; library code lives in
  `functions/_lib/review/` and exports no `onRequest*`, so it is never a route (a test checks).
  Decisions are JSON POSTs with a same-origin check (`Origin` must match; a cross-site form can't
  send `application/json`), the Access cookie being the only credential.
- **JWT verification in the Function, not just Access in front:** Access protects
  `pontonomada.pt/review`, but the production `ondestaanocas.pages.dev` host is only redirected by
  a Bulk Redirect, not protected, so a request could reach the Function without passing Access and
  with a forged `Cf-Access-Jwt-Assertion`. Every request therefore verifies the token: RS256 only
  (no `alg: none`, no HS256), signature against `https://<ACCESS_TEAM_DOMAIN>/cdn-cgi/access/certs`
  (keys cached per isolate for an hour; an unknown `kid` refetches at most once a minute, so
  forged kids can't hammer the endpoint), `aud` containing `ACCESS_AUD`, `iss` =
  `https://<ACCESS_TEAM_DOMAIN>`, `exp` in the future, `nbf` (60 s skew), and an `email` claim,
  which becomes the event's `actor`. Missing settings fail closed. Refusals are 403 in pt-PT.
  WebCrypto only; the clock, fetch, UUIDs and the key cache are injected, so vitest signs tokens
  with a generated RSA key.
- **Type check:** `npm run typecheck` (CI, before the tests) runs `tsc` strict twice, with
  `typescript` 5.9.3 and `@types/node` 22.20.4 pinned as dev dependencies:
  `tsconfig.functions.json` checks `functions/` and the `src/lib` modules it imports with web
  platform globals only (no Node types, so a `Buffer` or `node:` import fails here instead of in
  the Workers runtime); `tsconfig.typecheck.json` checks `src/lib` and the tests with Node types.
  `.astro` templates are left to the build. It caught WebCrypto's `BufferSource` wanting an
  `ArrayBuffer`-backed `Uint8Array` in `access.ts`.
- **Handler seam:** `handler.handle(request, env, deps)` is pure; the tests (`web/test/review/`)
  drive it with an in-memory R2 stub (paginated listing), a fake fetch for the certs,
  Travelpayouts and GitHub, and validate every written event against
  `contract/review/v1/event.schema.json` with ajv. They assert exactly one dispatch per decision,
  none when the event can't be stored, and the pt-PT message when GitHub fails.
- **Events** have the Python writer's shape and key (`review/events/pending/<YYYYMMDDTHHMMSSZ>-<uuid
  v4>.json`, `created_at` to the second with `Z`, note and post link stored as sent with only an
  empty one becoming null, exactly like `Event.new` (`note or None`; the pages trim before
  sending; cases in `review-rules.json`), `post_url` only on `published`, `live_check` only on
  `approve`). Before writing, the Function applies the same
  pre-checks as `pipeline._decidable` against the snapshot: the transition table and the
  affiliate-link and post-URL rules (`rules.ts`, a port of `review.check_decision` with the same
  pt-PT messages) and "one pending decision per deal". The ported tables (`TRANSITIONS`,
  `STATUS_PT`, `DECISIONS`, `DECISION_PT`, `db.OPEN_STATUSES`) and `check_decision` cases live in
  `contract/review/v1/fixtures/review-rules.json`, checked against both sides
  (`tests/test_review_rules_cases.py`, `web/test/review/rules.test.ts`), so they can't drift. Pending = the snapshot's `pending_events`
  plus objects under `pending/` whose name is not older than the snapshot's `generated_at`: an
  older object missing from the snapshot was already applied by the run that made it (D26 keeps it
  pending until the next run), so it must not block, e.g., marking a just-approved deal
  published. The applier re-checks everything anyway.
- **Dispatch:** after the event is stored, one `POST /repos/<GITHUB_REPOSITORY or
  MiguelCorre/escapadinha>/dispatches` with `event_type: review-decision` and `{event_id,
  deal_id, type}` (the workflow ignores the payload: a dispatch run applies every pending event
  and takes the full path, D25). No retry: a failure is reported ("a decisão ficou guardada;
  aplica-se no próximo run") and the event stays for the next scheduled run, so it is never lost
  or written twice. GitHub keeps at most one queued run per concurrency group, which is fine: any
  run applies all pending events.
- **Live check port:** `live-check.ts` reimplements `travelpayouts.parse_response` (local dates
  from the link, `search_date`, nights range, positive numeric price) and `recheck.recheck` (rule
  check, same trip, first cheapest, price rose, freshness by found date else fetch day, same pt-PT
  reasons and `eur` text with a plain space) on the snapshot's `live_check.query` and `.rules`;
  the token goes in `X-Access-Token`. The shared cases in
  `contract/review/v1/fixtures/live-check-cases.json` run through both (`tests/
  test_live_check_cases.py`, `web/test/review/live-check.test.ts`). When the provider can't
  answer, both sides give the same pt-PT reason without English or response text
  (`pipeline.check_failure` / `checkFailure`, from `TravelpayoutsError.kind` / `ProviderError.kind`:
  rate limited, HTTP error with its status, error in the payload, no answer, no token; the
  technical text stays in the run's error or on `CheckError.detail`); the `failures` cases in the
  same file drive a real request on each side. The Function's other messages (GitHub dispatch,
  storing the event) are pt-PT the same way. The deal's own stop limit uses its observation's
  counts, which the snapshot carries since this ticket (`transfers` / `return_transfers`, optional
  fields added within v1, exported by `review_snapshot.py`), exactly like `RouteRules.allows`
  (unknown counts never pass a limit); only a snapshot made before them falls back to `direct`
  (a non-direct deal counts as one stop each way). Shared cases cover both. One known difference:
  no retries on 429/5xx (the pipeline waits up to a minute; on the phone Miguel taps again).
- **Page:** pt-PT, one column (max 680 px, 16 px gutters, checked at 375 px with no horizontal
  scroll), slides in a swipeable strip, 44 px buttons, `noindex` (meta and `X-Robots-Tag`),
  `Cache-Control: no-store` (slides `private, max-age=600`). Same information and copy as the local
  page plus the WhatsApp text and caption with copy buttons, the snapshot time (warning past 3 h),
  pending decisions, recent outcomes and the 24 h approval rule from `review_rules`. pt-PT formats
  come from `web/src/lib/format.ts`; the pt-PT lint test now scans `web/functions/` too. Colours,
  radii and the focus ring are the design system's (`TOKENS` from the generated
  `web/src/lib/tokens.ts`, a plain module wrangler bundles; both palettes as `--pn-*` variables):
  square cards and buttons, inputs with a 4 px radius and an `ink` border (§2: anything a user must
  see is `ink` or `accent`, `rule` is decorative), notices with the state colour as a left rule
  over its tint. The web fonts aren't served to the Function, so the text stack's Georgia shows.
- **Deploy wiring** (the staging folder was replaced at the cutover, D35: wrangler now runs in
  `web/`): wrangler compiles `<cwd>/functions` during `pages deploy`, and the deploy ran
  with cwd = `site/`, so Functions were never uploaded. `website/deploy.py` now stages a temporary
  folder with `functions/` and the `web/src/lib/` modules they import (`function_files`: transitive
  relative imports, whether `import … from`, `export … from`, side-effect `import "./x"` or dynamic
  `import("./x")`; a bare package import or a missing file is a `DeployError`; listed once per
  deploy and shared by the hash and the staging), runs wrangler
  there with the site's absolute path, and deletes it. The staging folder holds nothing else, so
  wrangler still never scans the repository (D15), and no `npm ci` is needed on the runner
  (wrangler bundles TypeScript itself; Node 22 is already set up). Rejected: running wrangler from
  `web/` (its `package.json` invites framework auto-detection, the D15 failure) and building a
  `_worker.js` into `site/` (advanced mode, a second wrangler step). The deploy hash
  (`deploy_hash`) adds those files (line endings normalised) to the site's content hash, and
  `run_path._code_files` includes them, so a Function change takes the full path and redeploys.
  The first deploy after this change uploads once more, as the hash's meaning changed.
- **Bindings** (Pages project, Production, set by Miguel): `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`,
  secrets `GITHUB_DISPATCH_TOKEN` (fine-grained PAT, this repo, Contents read/write) and
  `TRAVELPAYOUTS_TOKEN`, R2 binding `STORE`. Preview deployments sit behind a separate Access app.
- **Verification on the phone** is a manual step for Miguel: `docs/runbooks/review-phone.md`.

## D30: Route pages, origin pages and destination hubs (2026-10-14, #14)
- **What:** the Astro site (D28) gets one page per route at the contract's `path`
  (`/voos/<origem>-<destino>/`, the Jinja site's URLs, so old route links keep working with no
  redirect), one per Portuguese origin at `/partidas/<origem>/` and one hub per destination at
  `/destinos/<destino>/`, plus the index pages `/partidas/` and `/destinos/` and a "Destinos" nav
  link. All generated from the contract; the web package never builds a path or a slug.
- **Contract, additive within v1:** `origins[].path` and `destinations[].path` (required in new
  exports, fixtures regenerated) and `routes[].calendar`. Slugs are computed once in Python next to
  `route_slug`: `website.origin_slug` and `website.destination_slugs`, which gives cities whose
  pt-PT names share a slug in one export their code too (`sao-jose-sjo`, `sao-jose-sjc`), so
  their URLs don't depend on which was found first (no collision in the real data on 2026-10-14:
  156 destination codes, 156 names). Route slugs are unchanged (`route_slug`).
- **Destination slugs are stable once published (review fix):** the first version re-slugged an
  existing hub when a same-name city appeared later (`/destinos/san-jose/` → `san-jose-sjo`).
  `site_data.export_site_data` now records every hub's path in the `site.paths` history (meta,
  key `destination:<code>`, the same mechanism as the Jinja pages' 301s, D19/D25,
  `record_destination_paths`), and the next export keeps each hub at the latest recorded slug
  that still fits its name (the name's slug or with its code); only the newcomer takes its code
  (`londres-xlo`). A slug changes only when the city's name does; its old path stays in the
  history, so `redirects.plan_redirects` gives the 301 (tested: collision introduced after the
  first export, then a rename). The Jinja build ignores these keys (it has no hubs); the cutover
  (#23) must add the `destination:<code>` pages to the Astro site's `_redirects` plan.
- **Calendar of cheapest found prices** (story 34, left open in D27): per departure date from the
  export day on (the Lisbon date of the export's `now`, the same `today` the pontes use: at 23:30
  UTC in summer it is already the next day in Lisbon, tested), the cheapest offer of the latest run within the route's rules and found within
  `max_offer_age_days`, i.e. the same offers as `cheapest`, broken down by day: `{dep, ret, obs,
  price}`, ascending. Only current offers, never old history, so a day's price is one a traveller
  saw in the last 3 days. `test_site_data.py` traces each day to its observation (and its
  departure date); the web traceability test adds them to the observation amounts. **Real data on
  2026-10-14 (run 30): 402 calendar days over 360 routes** (about one per route; `routes.json`
  223 KB), because few offers were found by a traveller in the last 3 days (all runs' fresh offers
  give 409, so it's the freshness window, not the latest-run rule). The calendar fills up as
  collection goes on; widening the window (e.g. every offer of the latest run whatever its found
  date) is a one-line change in `site_data._calendar`, rejected for now because a cell can't show
  how old its price is and stale prices are what the freshness window exists to keep out. The
  synthetic scale data has ~50 days per route (1.5 MB `routes.json`, build-time only, never shipped
  to visitors) as the worst case.
- **Route page:** kind, title "Voos de <origem> para <destino>", which offers count (`rules`), a
  **dormant notice** (`status: dormant`, with the last price seen, the page kept as a record),
  "mais barato agora" (`cheapest`), live promotions (cards), recent **low prices** (the biggest
  `LOW_PRICES_PER_ROUTE` = 5 discounts by departure date, a live promotion's own offer left out,
  as on the Jinja page: each with `data-obs`, the discount, the typical low it was measured against
  under `data-route`, dates, airline, stops, arrival airport with the remote tag, "Encontrado por
  um viajante a" found date and "visto por nós a" first fetch (the explorer's row, D31), and its
  own partner link from the contract with
  `rel="sponsored nofollow noopener"`; the site disclosure sits under the list inside the same
  `data-cta` block), the **calendar** (Monday-first month grids, each priced day `data-obs`, the
  month's cheapest marked), the **typical low per month** with the plain average as context and
  the days behind it; a month below `min_baseline_days` says "ainda sem dados suficientes" and
  "2 de 4 dias" instead of a number. Then recently expired promotions and links to the hub and the
  origin page. Rejected: a booking link per calendar day (one more partner link per day would blow
  the per-run link budget of D24 for little gain; the low prices above carry the links).
- **Origin page:** every route from the airport grouped by kind (Europa, Portugal, Longo curso),
  each by city name (pt collation), with the cheapest price found now (`data-obs`) and dates, or
  "sem preços recentes", or the dormant tag. Price order is the explorer's job (#15).
- **Destination hub:** every Portuguese origin with a route there, in the contract's origin order,
  with its route page, cheapest price, **best months** (`BEST_MONTHS` = 3 months with the lowest
  typical low, cheapest first, under `data-route`; "Ainda sem dados suficientes" otherwise), a link
  to the origin page; the origins we don't watch for that city are named; arrival airports with
  the remote tag; live promotions to the city. No photo yet: destination photos are files under
  `assets/photos/` the web package doesn't copy (D27 open question, the cutover #23).
- **Itinerary hook for #17:** `src/lib/itinerary.ts` (`itineraryFor(code)`, always null now) and
  `ItineraryLink.astro` on route pages and hubs; #17 swaps the body for a lookup in its reviewed
  content collection, the pages stay as they are. The live search widget is #16.
- **One place for pt-PT words and day arithmetic (review fix):** month and weekday names, "terça-feira,
  1 de dezembro de 2026" (`longDateYear`), month labels (`monthYear`) and the calendar's column
  names come from `src/lib/format.ts`; weekday, nights between two days, days in a month and the
  Lisbon day of an instant from `src/lib/dates.ts`, shared by the route pages, the explorer, the
  island and the ponte pages. A test fails on a month or weekday name spelled out anywhere else
  in `web/src/`.
- **Tests:** `web/test/routes.test.ts` (the view logic in `src/lib/routes.ts` on hand-made
  routes: month rows, best months, calendar weeks, low-price selection, groups, rules text),
  `route-pages.test.ts` (the fixture build: every contract path built, every route page linked from
  its origin page and hub, months without data, calendar traced, low prices with found date and a
  sponsored link next to the disclosure, best months), the internal-link test (`brokenLinks`: every
  `a`/`link`/`img` to an internal path resolves to a built page or file), and the traceability test
  now also on the new pages. The traceability checker and link check moved to `test/trace.ts` and
  `test/html.ts` to be shared with the scale test.
- **Scale and build budget:** the fixtures have 10 routes, so `web/test/scale.test.ts` writes a
  synthetic contract dataset the size of the real data (`test/synthetic-data.ts`: 360 routes from
  the 6 origins as on 2026-10-14, 156 destinations, dormant routes, months with and without enough
  days, ~50 calendar days per route, low prices, one live and one expired promotion;
  `meta.fixture: true`, cities "Destino de teste AB", codes `Z..`, example.com links, seeded made-up
  prices that only ever exist in a temporary build), validates it against the schemas and builds
  it: 528 pages (360 route, 6 origin, 156 destination pages) in ~5 s on Miguel's PC (~18 s on a
  cold first build); the test fails above **120 s**. It also checks the dormant notice, the months
  without data, internal links and price traceability on every page at that size. The fixture
  build takes ~2 s.
- **Lighthouse:** one URL per new page type added to `web/lighthouserc.json` (`/voos/lisboa-paris/`,
  `/partidas/lisboa/`, `/destinos/paris/`), thresholds unchanged. Local run 2026-10-14 (fixture
  build, median of 3, two runs): route 0.91 / 0.93, origin 0.95 / 0.95, destination 0.95 / 1 performance; accessibility, best
  practices and SEO 1 on all three (home and promotions 0.94 / 1 / 1 / 1). The route page's FCP is
  ~2.6 s under simulated throttling, close to the 0.9 line; the full-size synthetic build's largest
  route, origin and hub pages measured 0.92–0.98 (the same FCP, pages ~85 KB with ~24 KB inlined
  CSS). If CI starts failing on the route page, look at the inlined CSS and the logo SVG first
  (~14 KB in every page).
- **Fixtures regenerated** from the current database (run 30, 2026-10-14): promotion 8 (LIS-FNC) is
  now the live one and 3 (LIS-PAR) the expired one, `base_url` is `https://pontonomada.pt`; the
  web tests and the Lighthouse URLs follow. Still no dormant route in the real data, so dormant
  pages are tested on the synthetic build.

## D31: Explorer, weekends and Portuguese long weekends (pontes) (2026-10-14, #15)
- **Calendar in the repo, Python owns it:** `content/holidays.yaml` lists the national holidays
  of 2026 and 2027 (Código do Trabalho art. 234.º as amended by Lei n.º 8/2016; Terça-Feira de
  Carnaval as `optional`, art. 235.º; Corpo de Deus and the other movable dates from each year's
  Easter), with the source in the file. Municipal holidays (Santo António, São João) are left
  out: they are not national. `pontes.py` (pure, plus a loader that refuses a day listed twice)
  derives each holiday's long weekend: Monday → Sat–Mon, Tuesday → Sat–Tue with Monday bridged,
  Thursday → Thu–Sun with Friday bridged, Friday → Fri–Sun; Wednesday, Saturday and Sunday give
  none (a five-day "double bridge" is not a ponte most people get). Easter Sunday therefore has no
  page of its own; Good Friday's ("Fim de semana da Páscoa") covers it.
- **Travel window = the weekend rule generalised:** from the evening before the first day off to
  the morning after the last one (a plain weekend is out Friday/Saturday, back Sunday/Monday).
  A low price fits a ponte when its departure and its return both fall inside the window
  (`start ≤ departure < return ≤ end`), as the spec says. (Review fix: the first version also
  required the trip to span the holiday, `departure ≤ holiday ≤ return`; that is not in the
  spec and is dropped, so a Friday-to-Sunday trip inside a Tuesday ponte's window counts.
  Tested on a Tuesday and a Thursday holiday.)
- **Contract, additive within v1:** `pontes.json` (`pontes.schema.json`) with every ponte of the
  calendar's years, past ones included, each with holiday, days off, bridge, window and one
  `{iata, path}` per origin; `meta.files.pontes` is optional, and the site reads an export
  without it as having no pontes. Paths `/pontes/<slug>-<year>/<origin-slug>/` come from Python
  (`website.ponte_path`, `website.origin_slug`; the web package never slugifies). **Raw values
  only (D27, review fix):** the first version exported a pt-PT `title` per origin built with a
  hard-coded article map (`i18n_pt._ARTICLE`); the title is now the site's
  (`format.ponteTitle`: "Ponte de 1 de dezembro desde o Porto", `format.fromPlace`) and the
  article comes from config `origins_article` (`OPO: o`, `FNC: a`, `TER: a`; Lisboa, Faro and
  Ponta Delgada take none), exported as `origins.json` `article` (optional, additive; `null` =
  none). Dropping `title` is not a v1 break for any consumer: `pontes.json` only exists on the
  unreleased M3 branch and the web package is its only reader. No prices in the
  file: the site selects the rows of each origin's low-price file, so traceability is unchanged.
  The committed fixtures got `pontes.json` and `meta.files.pontes` computed at the fixtures'
  own `generated_at` instead of a full regeneration, which would have replaced every fixture
  with the newer database (other tickets' expectations); the next `export fixtures` writes the
  same file (the review fixes recomputed `pontes.json` and the origins' `article` the same way).
  The calendar is under `content/`, which the run-path fingerprint already hashes, and the "day"
  component turns a ponte "past" on the site the day after its window.
- **Weekend and ponte matching live in the web package** (`web/src/lib/explorer.ts`), because the
  island needs them in the browser and the pages at build time; one module, tested in vitest
  (`isWeekendTrip`; `fitsPonte`). Python tests the calendar and the windows
  (`tests/test_pontes.py`).
- **Weekend rule, 1 to 3 nights:** a weekend trip leaves on Friday or Saturday and comes back on
  the Sunday or Monday **of the same weekend**: Saturday-Sunday is 1 night, Friday-Monday 3.
  The 1–3 night cap is what "the same weekend" means in code: without it, Friday out and Sunday
  back nine days later would match the weekdays. The explorer's checkbox says it in full: "Só
  fins de semana (partida sexta ou sábado, regresso domingo ou segunda, até 3 noites)". Kept as
  is in the review (a cap of 2 would drop Friday-Monday, which most people count as a weekend
  away; pontes cover the longer ones).
- **Explorer `/explorar/`:** server-rendered default list (the first origin with low prices,
  each destination at its cheapest, sorted by price, "+N datas") that works without JavaScript;
  the filter form is in the page from the first paint (hidden by `<noscript>` without JS, so the
  island causes no layout shift). The island is vanilla TypeScript (~5.4 KB, 2.7 KB gzipped):
  it fetches `/explorar/dados/<ORIGIN>.json` (static endpoints: the contract rows as they are plus
  destination and airport names) only when that origin is needed, caches it, and redraws with the
  same `resultsHtml` the server used, so every result keeps `data-obs` on its price, `data-route`
  on its typical low, the found date, the arrival airport and the tracked link; the site
  disclosure and the CTA note sit once above the list in its `[data-cta]` block. No framework:
  one list and a form don't need one. Filters live in the form only (no URL state yet).
- **One low-price row everywhere (review fix):** the explorer, the ponte pages, the island and
  the route pages draw a low price with the same function, `src/lib/low-prices.ts`
  (`lowPriceView` + `lowPriceHtml`; the explorer adds the destination as headline and "+N
  datas"): price (`data-obs`), discount, dates and nights, airline and stops ("voos diretos",
  `format.stopsText`), arrival airport (remote tag), "Mínimo habitual em <mês>" (`data-route`),
  "Encontrado por um viajante a <found date> · visto por nós a <first fetch>" and the button by
  the `cta.ts` rule (`bookingLink`: the contract's link, https only, `CTA_TEXT`/`CTA_REL`; the
  site disclosure and `CTA_NOTE` once per list). The route pages had their own wording ("Ver
  voo", "Encontrado a", no https check); a test compares a row on `/explorar/` with the same
  offer on its route page. The per-origin files carry airline names too (`places.airlines`), and
  `originFile` runs every row's link through the https rule at build time, so the island never
  meets a link the server would refuse. Island: 6.6 KB (3.2 KB gzipped).
- **A row without a stored partner link** (D24: links are created a few hundred per collection
  run, the rest wait for the next run) shows everything else, found-on date included, and "Ligação
  de reserva disponível em breve." (`cta.NO_LINK_NOTE`) where the button would be, on route pages,
  the explorer and the ponte pages alike.
- **Results link to route pages** (after merging #14): each result's headline links to its
  route page `/voos/<origem>-<destino>/`, the contract's route `path` carried in the per-origin
  files' `places.paths` (no link when a row's route is missing). Origin page and ponte pages share
  one slug function (`website.origin_slug`): `/partidas/porto/` and `/pontes/<feriado>/porto/`.
- **Ponte pages** `/pontes/.../...` per ponte × origin (16 pontes in 2026–2027: 96 with six
  origins, past ones included): holiday, days off,
  bridge day, window, the optional-holiday warning for Carnaval, the matching low prices, the
  other origins' pages and the legal source; `noindex` while nothing matches. **Past pontes keep
  their pages** (review fix: dropping them from the export turned indexed pages into 404s): a
  ponte whose window ended before the Lisbon date of `meta.generated_at` (`isPastPonte`) is built
  `noindex`, without prices, with "Esta ponte já passou." and a link to the upcoming ones; the
  explorer's filter and list offer upcoming pontes only (`upcomingPontes`). No fixture trip
  fits a ponte (real data), so the built pages are all the empty state; the listing itself is
  `resultsHtml`, covered with test rows.
- **Lighthouse** (local, 2026-10-14, mobile, median of 3): explorer 0.92 / 1 / 1 (perf / a11y /
  SEO), ponte page 0.95 / 1 / 1; both URLs are in `web/lighthouserc.json`.

## D32: Posting queue with daily slots, dry-run publisher, WhatsApp text (2026-10-14, #20)
- **Why:** after approval a promotion should reach Instagram, Telegram and WhatsApp without Miguel
  posting by hand, but never as a burst ("the feed never looks like a bot", story 54) and never
  once it expired (story 55). The real publishers come later (Instagram #24, Telegram #21); this
  ticket ships the queue, the publish step and a dry-run publisher.
- **Table** `posting_queue` (schema v10, migration 10 + `schema.sql`): one row per promotion and
  channel (`UNIQUE (deal_id, channel)`), `channel` `instagram` | `telegram`, `due_at` (UTC),
  `status` `queued` | `published` | `cancelled`, `event_id` of the approval, `checked_at` (that
  approval's live price check, `live_check.checked_at`), `attempts` and
  `last_error` (publisher errors, or why a due post waits), `publisher` (`dry-run`, later
  `instagram`/`telegram`), `result_url`, `reason` (pt-PT, why cancelled), `settled_at`.
  Published and cancelled are final. `checked_at` was added to the v10 table itself (review fix):
  v10 never reached a released database (master and the real database are v9).
- **One list of channels:** `posting.CHANNELS` is the only place the channels are named: the
  config's `posting.publishers` validation and default, and the planner of an approval's posts,
  read it; the SQL `CHECK` (in `schema.sql` and migration 10) can't, so a test compares both
  with it. What a run does with a post is typed: `posting.VerdictAction` (`publish`, `later`,
  `wait`, `cancel`) and `posting.PostAction` (`published`, `cancelled`, `waiting`, `failed`,
  in `pipeline.PostResult`, which the CLI matches on). The queue is read with `db.posts`
  (the `pipeline.posts` pass-through is gone).
- **Enqueue = applying an approval.** `review_events.apply_pending` takes `plan_posts` (passed in
  by `pipeline.apply_review_events`); when an `approve` event is applied, its posts are written by
  `db.settle_review_event` in the same transaction as the status change and the outcome, so an
  approval is never applied without its posts (and a re-applied event, D26, queues nothing twice).
  Approvals made before v10 queue nothing: those were posted by hand.
- **Slots** (`posting.next_slot`, pure, `now` passed in): Instagram gets the first daily slot at
  or after the application time that no queued/published Instagram post holds, on a Lisbon day
  with fewer than `max_per_day` such posts (a cancelled post frees its slot). Config
  `posting.instagram_slots` (default `09:00`, `13:00`, `19:00`, Lisbon time) and
  `posting.max_per_day` (3). "Today" is the Lisbon date; slots are converted with `zoneinfo`, so
  09:00 is 08:00 UTC in summer and 09:00 UTC in winter. A slot inside the clock change hour reads
  with `fold=0`: one skipped in March is taken with the winter offset (01:30 → 02:30 summer
  time), a repeated one in October is the first. Tests cover both last Sundays and the
  Lisbon-vs-UTC midnight. Telegram is due at the application time ("immediately").
- **Publish step** (`pipeline.run_publish`, CLI `publish_due`): **every run, after `detect` and
  before `run_path.decide`**, so posting never waits for a full path (an approval takes the full
  path anyway, D26; a 13:00 slot usually comes on a fast run). It sits after the recheck so the
  promotion's status is this run's: for every queued post, `posting.verdict` cancels it when the
  promotion expired ("A promoção expirou: <reason>."), was rejected, or (Instagram only) was
  already marked published by hand, whether or not it is due; a due post goes out only if the
  price was verified (last recheck, else the approval's live check: the event's
  `live_check.checked_at`, kept on the post as `checked_at`, not the approval time, which can
  be later; tested) within
  `posting.max_check_age_hours` (6), otherwise it waits with the reason (e.g. this run's
  collection had no prices for the route). At most one Instagram post per run, so a backlog
  after failed runs goes out two hours apart. A run whose collection failed exits before this
  step: nothing is posted without a recheck.
- **A published promotion is not rechecked any more** (only `db.OPEN_STATUSES` are), so a post
  that waits for a recheck would wait forever (review fix). When Miguel marks a promotion
  published, its Instagram post is cancelled as before; a post on another channel (Telegram)
  still goes out if the last verification (a recheck made while it was approved, else the
  approval's live check) is within the 6 h, and once that window has passed it is **cancelled**
  with "A promoção foi marcada como publicada e já não é verificada: o preço confirmado tem mais
  de 6 h." instead of waiting. `posting.verdict` applies this to any status the run no longer
  rechecks; tested on both sides of the window.
- **Publishers** are pluggable (`posting.Publisher`: `name`, `publish(Message) -> Published(url)`,
  raises on failure). `Message` carries the post, deal, observation, headline, price, the text
  (Instagram: the caption from `deal_caption_text`; Telegram: the WhatsApp text) and the stored
  partner link. Config `posting.publishers` maps each channel to a name; only `dry-run` exists:
  it logs what would be posted (channel, deal, headline, price, slot in Lisbon time, full text)
  and makes no request; the post is settled `published` with `publisher = 'dry-run'` and no URL.
  A publisher error keeps the post queued (attempt +1, error in `last_error`);
  `posting.max_attempts` (5) errors cancel it. Nothing here changes a review status (D26): a real
  publisher that should mark the promotion published writes a `published` event (#24 decides).
- **WhatsApp text** (`captions.whatsapp_text`, template `captions/templates/whatsapp.txt.j2`):
  shorter than the caption, no hashtags, no discount claim; headline (a remote arrival airport in
  it), price, dates and nights, airline, arrival airport, "encontrado a <found date> e verificado
  a <fetched at> (hora de Lisboa)", the promotion's stored partner link (`deals.affiliate_url`,
  the Instagram Project, D19; WhatsApp has no Project of its own yet) and `presentation.DISCLOSURE`.
  Only for approved and published promotions with a link (`pipeline.whatsapp_for`). The review
  snapshot fills the existing `whatsapp_text` field (description updated, no shape change); the
  phone page already shows it with a copy button (D29) and the local review page now does too.
  The traceability test checks its prices like a caption's.
- **CLI:** `escapadinha queue list` (queued posts, Lisbon time, why a due one waits; `--all` adds
  published and cancelled ones with publisher or reason).
- **Rejected:** enqueueing in a separate step after the applier (an approval could be applied
  without its posts if the run died in between); posting several Instagram slots in one run;
  cancelling a post whose price was not re-verified (it waits for a run that verifies it).

## D33: Itineraries and tips as reviewed MDX content collections (2026-10-14, #17)
- **What:** two Astro content collections in the web package, `itineraries` and `tips`, MDX files
  in `web/src/content/itineraries/` and `web/src/content/tips/` (where the build and #19's drafts
  both find them). The file name is the slug and the only source of the page path:
  `/roteiros/<slug>/` and `/dicas/<slug>/` (`content.contentPath`, refuses a non-slug name), plus
  the listings `/roteiros/` and `/dicas/` (`noindex` while empty) and a "Roteiros e dicas" section
  on the home page (latest three of each, only when there are any). Hand-chosen slugs are not
  computed in Python like the contract's paths: they are not data, they are file names. No nav link
  yet: there is no reviewed content in a real build, and the nav would point at an empty page.
  `@astrojs/mdx` **8.0.2** (exact, newest release older than two weeks; peer `astro ^7.2.10`) is
  the only new dependency.
- **Front matter** (zod schemas in `src/lib/content.ts`, `astro/zod`, a plain module so vitest and
  tsc check it): `title`, `description` (≤ 200), `last_checked` (YAML date → ISO day),
  `sources` (`{title, url}`, https only), `best_months` (1–12), `reviewed` (default `false`),
  `fixture` (default `false`), `legacy_path` (an old site path); itineraries add `destination`
  (contract city code) and `days` (1–30), tips `topic` (a slug) and `destinations` (codes). A
  reviewed entry without `last_checked` or without a source fails the build: "nothing I have not
  read goes live" (story 47) and "state when facts were last checked and link official sources"
  (story 51) are schema rules, not conventions. Every file, drafts included, is validated on every
  build, because the loader reads them all; the gate decides only what is built. The spec's
  "affiliate blocks" (eSIM, insurance, activities) are #18's.
- **Review gate in one place:** `src/collections.ts` (`itineraries()`, `tips()`) filters with
  `content.isVisible`: reviewed entries; drafts too in `astro dev` (with a "Rascunho" notice and
  `noindex`, so Miguel reads them in the local preview); test-only entries (`fixture: true`) only
  when the site data is fixture data (`meta.fixture`). Every page, listing and the itinerary link
  read through it; a sitemap (not built yet) must too. The dev check is `import.meta.env.MODE ===
  "development"`, not `DEV`: Vite derives `DEV` from `NODE_ENV`, which vitest sets to `test`, and
  the first test build did ship the drafts that way (caught by `content-pages.test.ts`).
- **Articles** (`ContentArticle.astro`): kicker, title, lead, the MDX body (`.prose` spacing on the
  tokens), then "Factos verificados a 14 de outubro de 2026" (`format.dayMonthYear`) with a line
  that hours, rules and prices change, and the sources as plain links (`rel="noopener"`, not
  sponsored: they are official pages). Itineraries add duration (`count`), best months
  (`format.monthList`: "abril, maio e setembro") and a link to the destination hub when the city is
  in the data. No JSON-LD `Article` yet (the SEO work with the sitemap).
- **Itinerary hook (D30) wired:** `itineraryFor(code, entries)` is now pure over the gated entries
  (`ItineraryLink.astro` passes `await itineraries()`); one reviewed itinerary per city (two stop
  the build), and in the dev server a draft shows only where no reviewed one exists. Hubs and route
  pages of that city render the link (`[data-itinerary]`).
- **No prices in content** (CLAUDE.md, never fabricate prices): an article can't carry an
  observation id, so it carries no amount at all. If an article ever needs a price, it must be a
  contract value rendered by a component with its `data-obs`/`data-route` (the traceability test
  already walks these pages), never text in the MDX.
- **pt-PT lint over content:** `web/test/pt-lint.test.ts` lints every MDX file (real, drafts and
  test-only): front matter values (YAML comments and `last_checked` skipped) and body, URLs
  removed; the Brazilian and English word lists, plus: "€", "EUR" or a number followed by
  "euro(s)"; a dot inside a number ("3.5 km"; pt-PT writes "3,5" and "1200"); ISO dates; a
  capitalised month after a day ("6 de Novembro"); English month names; "20 %"; "9 am"; the pt-BR
  progressive gerund ("estou visitando" → "estou a visitar"). A seeded "você" fails it (in a
  string and in a seeded file).
- **Old guide converted:** `content/guides/voos-baratos-dicas.yaml` (never published: it was
  `reviewed: false`, with no sources) is now the tip `web/src/content/tips/voos-baratos.mdx` with
  its five tips as sections, **still a draft** (no `last_checked`, no sources): it renders in the
  dev server at `/dicas/voos-baratos/` and goes live when Miguel checks it, adds sources and sets
  `reviewed: true`. Its front matter keeps `legacy_path: /guias/voos-baratos-dicas/` for the
  cutover (#23) to turn into a 301 (any entry's `legacy_path` → its new path). The Instagram-only
  fields (kicker, CTA, caption, hashtags) stay in the YAML, which still feeds the carousel
  renderer (`render guide`) and the Jinja site until #23 retires them.
- **Fixture content:** `web/test/fixtures/content/` holds a reviewed test itinerary for Paris
  (`paris-em-3-dias`, PAR is in the fixtures), a reviewed test tip (`dica-de-teste`, two sources,
  about PAR)
  and a draft itinerary for Barcelona, all `fixture: true`, saying in their text that they are test
  content, with example.com sources. They make the fixture build (and Lighthouse) exercise the
  pages; a build from real data never includes them. `content-pages.test.ts` checks: pages and
  listings for reviewed entries; drafts absent from the build, from every page's links and text;
  the checked date and source links; the MDX body; days, best months and the hub link; the link
  from `/destinos/paris/` and `/voos/lisboa-paris/`, none from Barcelona's hub (draft only).
- **Run path:** the Astro site is not deployed by `run` until the cutover; #23 must add the web
  package's sources, content included, to `run_path._code_files` so a newly reviewed article
  takes the full path.
- **Lighthouse:** `/roteiros/paris-em-3-dias/` and `/dicas/dica-de-teste/` added to
  `web/lighthouserc.json`. Local run 2026-10-14 (fixture build, mobile, median of 3): itinerary,
  tip and `/roteiros/` 0.95 / 1 / 1 / 1 (performance / accessibility / best practices / SEO), home
  with the new section 0.94 / 1 / 1 / 1.
- **Related tips on destination hubs (story 36, review fix):** a hub lists the reviewed tips whose
  `destinations` front matter names its city code ("Dicas para Paris", most recently checked first,
  `src/lib/related.ts` `tipsFor` over the gated `tips()`, `RelatedTips.astro`); nothing is rendered
  when there are none. The test tip now has `destinations: [PAR]`: `/destinos/paris/` links it,
  Barcelona's and Madeira's hubs show no section.
- **Not done here:** a nav link, JSON-LD and the sitemap (done in D34), affiliate blocks (#18), the
  drafts themselves (#19).
- **First drafts (#19, 2026-10-14):** five itineraries and five tips in `web/src/content/`, all
  `reviewed: false`, each with at least three official https sources and `last_checked`. The
  issue asked for "the destinations with the most published promotions", but nothing is
  published yet, so the destinations come from the data instead (read-only on the 2026-10-14
  database, generation 30, run 42): the active routes' low prices in the latest completed run
  (`pipeline.route_low_prices`) per destination city. Exactly five cities had any: Barcelona 5,
  Madeira 3, Paris 2, Ponta Delgada 1, Roma 1 (promotion candidates: Madeira 3, Paris 3,
  Barcelona 2): city breaks in Spain, France and Italy plus Madeira and the Azores. All five are
  inside the EU, where roaming costs what it does at home, so no itinerary has an eSIM
  block; the eSIM tip does. Activities (Tiqets) go in every itinerary, insurance in the hiking
  ones (Madeira, São Miguel) and the insurance tip (it renders nothing until a programme is
  configured, D37). Facts are only what the cited pages say; what could not be read
  automatically (sites refusing bots or rendered with JavaScript) or needs Miguel's decision is a
  `# TODO Miguel` YAML comment in the front matter (the lint skips YAML comments, the page never
  shows them). `best_months` is left empty: no official source states one. Compensation amounts
  (EU 261/2004) and fees (Madeira's trails) are not written: the lint refuses euro amounts, and
  the sources are linked instead. The review checklist is `docs/runbooks/rever-conteudo.md`
  (pt-PT); the drafts render in `npm run dev:fixtures` with the "Rascunho" notice.
  `content-pages.test.ts` now reads its draft list from `src/content/` (every entry whose front
  matter is not `reviewed: true`) instead of naming the old guide only, so no real draft can reach
  the build, a listing or a link, and approving one needs no test change.
- **Real reviewed content next to the test content (#19, 2026-10-15):** Miguel published the ten
  drafts, and the fixture build (which builds real reviewed entries too, so their pages are
  build-tested at PR time) stopped on `two reviewed itineraries for PAR: paris-em-3-dias,
  paris-em-4-dias`. **A test-only itinerary now wins over a real one for its city**
  (`itineraryFor`, `ItineraryEntry.data.fixture`): the gate passes test-only entries only in a
  fixture build, so this changes nothing in a real build, and approving a real itinerary for a
  city the test content uses never stops the fixture build; two reviewed real ones, or two
  test-only ones, for a city still do. `content-pages.test.ts` derives every expectation about
  real content from the files (front matter through the zod schemas and `isVisible`): each hub
  of the fixture data links its expected itinerary (test-only first) or none, lists exactly the
  built tips naming its city, and the home page links the first entries of `/roteiros/` and
  `/dicas/`. No test assumes the real content is all drafts any more.

## D34: SEO, structured data, search widget and analytics (2026-10-14, #16)
- **What:** the Astro site (D28) gets canonical, OpenGraph and Twitter tags on every page,
  `sitemap.xml` and `robots.txt`, JSON-LD, the About (`/sobre/`, "Como funciona") and Privacy
  (`/privacidade/`) pages carried over from the Jinja site and linked from every footer, the
  Aviasales search form on route and destination pages, and the Cloudflare Web Analytics beacon
  when a token is configured. The site sets no cookies.
- **Analytics (decided with Miguel):** Cloudflare Web Analytics already runs in **automatic setup**
  on the `pontonomada.pt` zone: Cloudflare measures at the edge, with nothing in our build and no
  cookies (19 page views counted in the 24 h before this ticket; in automatic setup Cloudflare may
  add its own beacon to the HTML it serves, which is its job, not the build's). So `site.analytics_token` stays
  `null`: a beacon too would count every visit twice. The code path stays for the day the
  automatic setup is turned off: with a token every page gets the official snippet
  (`<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token": …}'>`),
  without one no beacon at all; both are tested. The issue's "Ações do Miguel" step 1 (add a site,
  paste the token) is therefore not needed. The token is validated (16–64 letters and digits) in
  `config.py` and in the contract, so it can't break out of the attribute.
- **Contract, additive within v1:** `meta.json` gets `analytics_token`, `search_widget` (both
  `null` when unset) and `instagram_handle` (config `brand.handle`, the contact on the About and
  Privacy pages and the Organization's `sameAs`). Optional in the schema, always written by
  `export site-data`; **a fixture export always writes `null` for the first two** (a fixture build
  is unconfigured, so Lighthouse measures the site without third parties). The committed
  `fixtures/meta.json` got the three fields by hand, the values a regeneration writes (as in D31).
- **Search widget:** the embed must come from Travelpayouts' widget constructor (we never build
  `marker=` URLs by hand, Aviasales term 1.4, D12/D19). Config `site.search_widget` holds the
  `src` of the constructor's script; `config.SEARCH_WIDGET_HOSTS` (`tp.media`, `tpwgts.com`,
  `tpembd.com`, `tpemd.com`, `tpscr.com`: the hosts the constructor's script embeds use) and the
  same list in the schema's pattern (a test compares them) accept only an https URL on one of them,
  with no quote, space or angle bracket. **The widget must be ours** (code review, 2026-10-14): the
  URL's affiliate Project, `trs=`, must equal `affiliate.project_for("website")` (585209; checked
  when config.yaml loads, `AppConfig`), and its `shmarker=` must be our partner marker, or
  `<marker>.<sub id>` (the constructor's sub id form). The marker is not in config.yaml: it is the
  `TRAVELPAYOUTS_MARKER` secret the partner links client already uses (`config.Secrets`), so that
  half is checked where the secrets are, `Context.search_widget()`, which the export calls; with no
  marker set (a checkout without `.env`) only the Project is checked. A widget made for the
  Instagram Project or copied from another account is refused with a `ConfigError` naming what
  differs (the marker's value is never printed), so it is never exported. `SearchWidget.astro` renders, on route and destination
  pages only, a "Pesquisar outras datas" section near the end of the page: a line saying these
  are the partner's live prices (ours are prices travellers found), a box with the src in
  `data-src` holding a **"Pesquisar voos no Aviasales" button** (`.btn`, the design system's one
  button) and an empty slot, a line saying the form only appears after the button is pressed and
  that the partner may then set cookies (linking to the privacy page), the site disclosure, and
  the loader. `src/lib/search-widget.ts` adds the `<script async>` inside the slot **only when the
  visitor presses the button** (once; the slot then reserves 22 rem and takes the focus, the
  button hides); nothing else (load, scroll, hover, focus) loads it, so no partner request and no
  partner cookie happens before an explicit action, which is what the privacy page says.
  Superseded (code review, 2026-10-14): loading it when the box came within 300 px of the viewport
  (IntersectionObserver, or the first scroll/tap/key press): the privacy page promised cookies only
  after a click or a search, and a scroll is neither. The component and its script render nothing when
  the src is null (Astro renders a component's script only where the template renders it; the
  fixture build has no trace of either, tested), and never on the home page, promotion pages or
  any other page. Miguel's steps (Tools → Widgets → Search form → Aviasales, Project "Pontonomada"
  585209, language pt, currency EUR, paste the `src`) are in `docs/runbooks/search-widget.md`.
  The widget's prices are drawn by the partner inside its own frame, not by us, so they are not
  ours to trace (D2 covers what our pages show).
- **No cookies:** the site writes none (no `document.cookie`/`cookieStore` in the built site, in
  `web/src/` or `web/functions/`, tested; the review Function's responses carry no `Set-Cookie`,
  and it is the only Function: public pages never go through one). The privacy page says so,
  describes the cookieless analytics (aggregate, no personal data, hence no consent banner) and
  that Travelpayouts/Aviasales may set their own cookies only after a click on a booking link or
  on the search button: the page quotes the button's text from `search-widget.ts`
  (`SEARCH_BUTTON`), so the two can't drift (tested).
- **Head tags:** canonical = contract `base_url` + the page path (as before); `og:type` `article`
  on itineraries and tips, `website` elsewhere; `og:image:alt` (the promotion's headline or the
  logo card, never a price); `twitter:title`, `twitter:description`, `twitter:image` equal to the
  OpenGraph ones. Their prices are traced like the title's (`data-deal` on `<head>`).
- **Sitemap from the built pages:** an Astro integration (`src/lib/sitemap.ts`, `astro:build:done`)
  reads every built HTML page's `<head>` and lists the canonical URL of each page without
  `<meta name="robots" content="noindex">`. Each page already decides its own noindex (expired
  promotions D28, empty or past pontes D31, empty listings and drafts D33, the 404 has no
  canonical), so the sitemap can't disagree with the pages and no rule is written twice. Rejected:
  `@astrojs/sitemap` (it lists every route and would need a filter repeating those rules) and an
  endpoint with its own list. The test compares the sitemap with the set of built pages without
  noindex. **Fixture build: 31 of 81 HTML pages** (home, 1 live promotion, 10 routes, 3 origins +
  `/partidas/`, 7 hubs + `/destinos/`, `/explorar/`, 1 itinerary + `/roteiros/`, 1 tip + `/dicas/`,
  `/sobre/`, `/privacidade/`); out: the expired promotion, the 48 ponte pages (no fixture trip fits
  a ponte, so all are noindex) and the 404. `robots.txt` is an endpoint (`Allow: /` and
  `Sitemap: <base_url>/sitemap.xml`), replacing the static `public/robots.txt`.
- **JSON-LD types** (`src/lib/structured-data.ts`, rendered by `JsonLd.astro`, `<` escaped):
  - Home: `WebSite` (name, url, `inLanguage` pt-PT, publisher) and `Organization` (name, url,
    `sameAs` the Instagram profile).
  - Live promotion: a `Trip` (name = headline, description, url, `tripOrigin` and `itinerary` as
    `Airport` with `iataCode`, two `subTrip`s "Ida"/"Regresso" with their `departureTime` dates)
    whose `offers` is an `Offer` (`price` = the offer's price as a number, `priceCurrency` EUR, `url`
    = the page). Why `Trip`: schema.org `Flight` (a `Trip` subtype) is about one scheduled flight
    and expects a flight number, departure and arrival times and the airline per leg; the API
    gives none of that per offer, and making them up would be fabricating. `Offer` is in `Trip`'s
    `offers` range, and `Trip` in `Offer.itemOffered`'s. No `availability`, `priceValidUntil` or
    `validFrom`: we don't know them. The block carries the offer's `data-obs` and `data-deal`.
    **Never on an expired promotion** (breadcrumbs only).
  - Itineraries and tips: `Article` (headline, description, `inLanguage`, `dateModified` =
    `last_checked`, author and publisher the Ponto Nómada `Organization`, `mainEntityOfPage`,
    url, image = the default OG image). No `datePublished`: we don't record one. Drafts get none.
  - `BreadcrumbList` on promotion, route, origin, destination, itinerary and tip pages, from the
    same list as the visible trail (`Breadcrumbs.astro`), so they never differ; the last crumb is
    the page itself (plain text on the page, its URL in the JSON-LD). Route pages now show the
    route as the last crumb, itineraries and tips got a trail ("Roteiros › …", "Dicas › …"), the
    promotion trail ends with the headline (remote airport included). "Promoções" is `/` in the
    JSON-LD (the visible link stays `/#promocoes`).
- **Validation, two layers:** (1) **compile time:** the builders are typed with **schema-dts
  2.0.0** (devDependency, types only, nothing shipped; the schema.org vocabulary generated as
  TypeScript; exact pin, 2.1.0 was 12 days old), so `npm run typecheck` fails on a property
  schema.org doesn't define for the type or a value of the wrong type (checked with probes: a
  misspelt `pricee`, `priceCurrrency` and a number as `tripOrigin` all fail). (2) **run time:**
  `web/test/jsonld.ts` has one JSON Schema per emitted type (ajv 2020, strict), listing exactly the
  properties we use (`additionalProperties: false`), plus our rules: https URLs on the base,
  ISO dates, `price` a number > 0, EUR, headline ≤ 110 characters, positions from 1. Every block on
  every built page must validate (an unknown `@type` fails), and seeded bad blocks must not. Not
  the online schema.org validator (no network in tests); worth one manual pass on the live site
  after the cutover (#23). Rejected: a JSON-LD processor with the full schema.org vocabulary file
  (a several-MB download committed or fetched in tests for the same check schema-dts gives).
- **Prices in JSON-LD are traced (D2):** `test/trace.ts` now reads every JSON-LD block: each
  `price`/`lowPrice`/`highPrice` must be a number and an amount of the block's own
  `data-obs`/`data-deal`/`data-route`, and each price string in its text ("69 €" in the
  description) is checked like any other; the live promotion page's count went from 6 to 10
  (Twitter title and description, the offer price and the Trip description). A test also checks
  the offer price against the fixture (obs 7226, 69 €) and the price the page shows.
- **About and Privacy:** content from the Jinja `about.html.j2`/`privacy.html.j2`, updated: every
  watched Portuguese airport (from `origins.json`) instead of "Lisboa e Porto", promotions "within
  the route's rules" instead of "direct only", the explorer and route pages' low prices, the
  analytics paragraph always present (the automatic setup measures whether or not a token is set),
  the search form. Contact: the Instagram handle from the contract. A separate contact page (in
  the spec's page list) is not made: contact is a section of both pages.
- **Tests:** `web/test/seo.test.ts` (fixture build: head tags, sitemap and robots, JSON-LD
  validity and per page type, prices, breadcrumbs against the visible trail and built pages,
  About/Privacy, no beacon, no widget, no cookie code), `seo-configured.test.ts` (a second build in
  the global setup, after the first: astro builds of one project can't run at once, they share
  `.astro/`; fixtures with `analytics_token` `fakeTestToken0000…` and `search_widget`
  `https://tp.media/content?fake=test-only&promo_id=0`: beacon on every page with the token,
  widget box on route and hub pages only, a `button.btn` with the partner's name and an empty
  slot, the partner's URL once and only in `data-src` (no script, iframe, img or link to a partner
  host), a click-only loader (no IntersectionObserver or scroll listener), the disclosure and the
  cookie note present, absent from everything else), `search-widget.test.ts` (the loader on a
  fake DOM: no element created and no script appended before the click, only a click listener,
  one script after it, none on a second click, focus moved to the slot), the JSON-LD traceability case, and Python: the export carries the three
  fields, fixtures never carry the token or the widget, the config refuses an http, foreign-host
  or quote-carrying widget URL, a missing, foreign or repeated `trs` and (with the marker set) a
  missing or foreign `shmarker`, and a non-alphanumeric token; the schema accepts the same hosts.
- **Lighthouse:** `/privacidade/` and `/sobre/` added to `web/lighthouserc.json` (12 URLs).
  Local run 2026-10-14 (fixture build, so no widget or beacon; mobile, median of 3; performance /
  accessibility / best practices / SEO): home 0.92, live promotion 0.92, expired 0.94, route 0.93,
  origin 0.95, destination 0.93, explorer 0.92, ponte 0.94, itinerary 0.95, tip 0.94, privacy 0.95,
  about 0.94 performance, and 1 / 1 / 1 on every URL; all assertions passed.
- **Not done here:** submitting the sitemap in Google Search Console (runbook brand-switch step 7,
  after the cutover), the Astro site's `_headers`/`_redirects` and deploy (#23), the widget's
  real `src` (Miguel, runbook).

## D35: Cutover to the Astro site (2026-10-14, #23)
- **What:** the Astro site (`web/`, D28–D34) replaces the Jinja site on the Pages project
  `ondestaanocas` (https://pontonomada.pt, D19). `run`'s full path is now render → `export
  site-data` into `web/src/data` (config `site.data_dir`, git-ignored) → `site build` (the Astro
  site, below) → `site deploy` (`web/dist` + the review Function) → `record_full_path`. The Jinja
  build is no longer part of `run` and nothing deploys it: it stayed as `site build-jinja`
  (`website/__init__.py` `SiteBuilder` + `website/templates/`) only until **phase 2**, which
  deleted it on 2026-10-21 after a week live with no broken link reported by `site crawl`
  (below). The shared helpers in `website/__init__.py` (slugs, `is_public`,
  `public_deal_rows`, `deal_image_paths`) and the modules below stay.
- **`site build` (`website/astro.py`):** `npm ci` only when `web/node_modules` is missing or
  was installed from something else: a stamp in node_modules, `.escapadinha-npm-ci`, holds the
  lockfile's sha256 **and the Node version, platform and architecture** (`node -e`, e.g.
  `v22.11.0 linux x64`), since native packages such as esbuild's binary are installed per
  platform; an upgraded Node on the PC or a node_modules copied from another machine installs
  again (deleting node_modules deletes the stamp too);
  then `npm run build` with `SITE_DATA_DIR` set to the export's absolute path (a stray variable
  pointing at the fixtures can't be what gets built; the old `web/dist` is removed first, so a
  failed build never leaves the previous one for the deploy). The review Function's imports are
  checked first (`deploy.function_files`, a package import is a `BuildError`), as the deploy does.
  **Node commands (`website/node.py`):** one small module, imported by both the build and the
  deploy, finds `npm`/`npx`/`node` (on the PATH, `npm.cmd`/`node.exe` through PATHEXT on Windows,
  else `C:\Program Files\nodejs\`, for the PC's scheduled task), puts the tool's folder first on
  the PATH, and runs it (`node.run`). It also holds `web/` and `web/dist` (`node.web_dir`,
  `dist_dir`) and `BuildError`, so `cli.py` imports the error without the build's imports (PIL,
  site data). **One time budget:** `run`'s full path takes one deadline (`node.deadline()`,
  `FULL_PATH_SECONDS` = 20 min) when it starts, and every Node command after it (npm ci, `npm run
  build`, wrangler) gets what is left of it as its timeout. A command that hangs (or can't start,
  or finds no time left) is a `BuildError`/`DeployError` with the end of its output, never a raw
  `TimeoutExpired`; the run fails, `export_review_snapshot` still runs and the database is
  pushed. Why 20 min: the job has 45 (D25) and the lock 60 (D21); a full path normally needs
  under 2 (~18 s npm ci, ~8 s build, a deploy of the changed files), the collection before it
  takes ~2 and the snapshot + push after it under 1, so 20 leaves more than 20 minutes for the
  rest even when the collection is slow (a test keeps `FULL_PATH_SECONDS` ≤ the job's timeout −
  20 min). Replaced: separate timeouts of 15 min per npm command and 10 min for wrangler, which
  could add up to 40 min and let the job be killed before the push. `site build` and `site
  deploy` run on their own get a budget each. Then the pipeline adds what the web package can't:
  - **promotion images** (D27/D28 open question): for every promotion in `promotions.json`,
    the slides the contract names are converted from the rendered folder
    (`pipeline.deal_folder(..., pipeline.SLIDES)`: on a runner each slide is downloaded once,
    D25) into `web/dist/img/promos/<id>/` (`slide_NN.webp`, `thumb.webp`, `og.jpg`;
    `website/images.py`, shared with the Jinja build); a path that couldn't be written is
    printed. **Destination photos** are not copied: no page shows one yet (D30), the contract
    only carries the credit.
  - **`_redirects` and `_headers`** (`website/routing.py`, the rules of `redirects.py`):
    `X-Robots-Tag: noindex` on the legacy hosts and per-deployment URLs as before (D19); there
    were no other headers to keep. Redirects (301, never on a built page, never to a path the
    build doesn't serve, both with and without the trailing slash):
    every older path of a page whose path changed, by stable key in `site.paths` (`deal:<id>`,
    `route:<key>`, `destination:<code>` from D30, and now `origin:<code>`; the build records the
    current paths, so a later rename gets its 301); `/promos/<id>` short aliases; a promotion the
    contract no longer lists (expired more than `site.expired_promotions_days` ago: the Jinja
    site kept those pages forever, D15) → its route page; `/guias/<slug>/` → the reviewed tip or
    itinerary whose front matter has that `legacy_path` (D33), else the tips index `/dicas/`
    (also for a history `guide:<slug>` no content names); `site.redirects` from config (one that
    would hide a page is printed and left out). A removed route stays an honest 404 (D19).
    **Hardened after code review (2026-10-14):** (1) a rule whose target isn't a page of the
    build is left out *before* the 2000-rule limit counts (it used to be filtered after the
    cap, so dead rules could take live ones' places); one rule per source; (2) **no chains:** a
    rule whose target is itself a source (e.g. a `site.redirects` entry to a promotion path that
    now redirects) points at the final page, a loop is left out (both reported); (3) **no silent
    drop:** within 10 % of Cloudflare's limit `site build` prints a warning, above it the build
    fails (`BuildError`) naming the way out (a Bulk Redirect, or pruning `site.paths`), where it
    used to drop the newest rules; (4) **bounded history:** a promotion the contract no longer
    lists is folded into its route's `site.paths` entry (its old paths and `/promos/<id>`
    become old paths of the route page, where they redirect anyway) and its `deal:` key dropped:
    the history stops growing a key per expired promotion, no build looks those deals up again,
    and a later route rename takes them straight to the new page (tested); (5) **paths only
    once live:** `routing.write` stores the build's history as `site.paths.pending`; `deploy`
    makes it `site.paths` after a successful upload, or when it skips an unchanged site (the live
    site is that build). A failed deploy, or a run without Cloudflare keys, records no path that
    never went out (tested). The D30 destination paths the export records are unchanged.
- **`site deploy`:** uploads `web/dist` (absolute path) with wrangler **running in `web/`**, so
  it compiles `web/functions` directly; the temporary staging folder of D29 is gone. D29 had
  rejected `web/` because its `package.json` might trigger framework auto-detection (the D15
  failure); checked in wrangler 4.149.0's source: autoconfig runs only for `wrangler deploy` and
  `wrangler setup`, and `pages deploy` delegates to Workers only for an agent run on a project
  that doesn't exist and has no Functions, neither of which applies. The Function must still
  bundle without npm packages (`function_files` refuses a package import, so it never depends on
  `node_modules` being there). **A fixture build is refused** (any page with
  `<html data-fixture="true">`, D28), and so is a missing build. The deploy hash is the content
  hash of `web/dist` plus the Function's sources (unchanged → skipped); the build's own
  timestamps don't count: the footer's `Atualizado a <span …>…</span>` and the explorer data's
  `generated_at`.
- **Full-path fingerprint (`run_path`, D25) covers what the Astro site shows:** the `low_prices`
  component (the Jinja route pages' five) is replaced by **`site_data`**: the whole contract as
  the next build would read it, computed in memory at decide time with `site_data.build_export(...,
  new_links=False)` (stored links only, nothing written; ~0.1 s on the real data), minus what
  changes on every run but no page shows: `generated_at` and the run id in `meta.json` and the
  low-price files, each route's observation count, its last-seen time beyond the day, which only
  a dormant route page shows as a date (a test fails if a page starts reading one of those).
  They are listed in `site_data.PER_RUN` and dropped by `site_data.shown_digest`, next to the
  export that writes them, so a new per-run field is classified where it is defined (code
  review: they were in `run_path._shown`, far from the fields); a test exports twice with the
  same offers, one run apart, and fails on any difference `PER_RUN` doesn't list. The **code** component adds the web package's sources (`web/src`
  without `web/src/data`, `web/public`, `web/functions`, `astro.config.ts`, `package.json`,
  `package-lock.json`) and what the build reads from outside `web/` (`assets/logo-light.svg`,
  `assets/fonts/*.woff2`), so a reviewed article, a template or a dependency change takes the
  full path; `node_modules`, `dist` and the export don't count. Promotions, routes and the day
  stay. The first run after the merge takes the full path (the stored fingerprint has no
  `site_data`). **Cost:** the export carries every route's cheapest fresh offer, calendar and
  every low price, which move more often than the five low prices per route page did. Replaying
  the last 13 runs of the real database (2026-10-13/14) the site data changed between 7 of them,
  the old `low_prices` component in 1: about half of the runs will take the full path (+ npm ci
  from cache, ~8 s astro build, a deploy of the changed files) instead of about one a day.
  That's still within the Actions budget (D25: ~720 of 2000 min/month for the fast paths); if it
  isn't, the knob is `site_data.shown` (e.g. leave the calendar to the daily refresh), not the build.
  Rejected: hashing `web/src/data` after the previous export (a runner has none, CI keeps no
  files) and comparing built sites (that is the cost the fast path avoids).
  **Recorded from the export that went live** (code review, 2026-10-14): `record_full_path(ctx,
  conn, export)` takes the `site_data.Export` the full path wrote, built and deployed, and stores
  its `shown_digest` and its day (`Export.generated_at`); it no longer rebuilds the export at
  record time. A full path can take minutes (npm ci, build, deploy): an offer that stops being
  fresh, or a new Lisbon day, in between would otherwise be recorded as published while the site
  still shows the earlier state, and the next run would wrongly take the fast path (tested with
  an offer that goes stale between the export and the record).
- **CI:** `actions/setup-node` (Node 22, no `cache:`), and npm's download cache (`~/.npm`) in
  two steps: `actions/cache/restore` before the run (key: OS, Node 22, the web lockfile's hash;
  falls back to the newest cache of an older lockfile), `actions/cache/save` after it, only when
  the run wrote `npm_ci=true` to `$GITHUB_OUTPUT` (`cli._github_output`: a full path whose npm ci
  and build succeeded) and the restore missed the exact key. Why not setup-node's `cache: npm`
  (code review, 2026-10-14): its post step saves whenever the key missed, so a fast path (no npm
  at all) after a lockfile change would save a nearly empty `~/.npm` under the new key, and every
  later full path would "hit" it and download everything. The **restore still runs on every
  run**, fast paths included: the run only knows after detection whether it takes the full path,
  inside one `escapadinha run` (lock → pull → … → push, D21), and splitting that process around
  the decision is not worth it. The cost is the download of ~/.npm for this lockfile (~363
  packages, tens of MB compressed; a few seconds), about 1 % of a ~2-minute fast path; skipping
  it would make each full path download from the registry instead. The fast path never runs
  npm. Timeout unchanged (45 < 60 min lock). The PC task needs Node 22+ installed (it already
  did for wrangler).
- **CLI:** `site build` (Astro, prints pages per type, images, redirects, size), `site
  build-jinja` (legacy, never deployed), `site preview` (serves `web/dist`; `_redirects` not
  applied), `site deploy` (refuses fixtures), `site crawl`.
- **No old URL may 404 (`website/crawl.py`, `site crawl`):** `check_build` resolves a sitemap's
  URLs against a build the way Pages does (a `_redirects` rule wins over a file; a redirect must
  land on a served page, not on another rule), `check_live` asks the live site without following
  redirects (200, or 301 whose target answers 200; 302/308/404/5xx and chains are reported).
  `escapadinha site crawl --sitemap <url|file> [--base <host>] [--dist web/dist]` prints the count
  and every broken URL and exits 1 on any. `tests/test_crawl.py` built (until phase 2) the
  legacy Jinja site and the **real** Astro site (npm, `web/`, into a temporary folder) from one database, with a
  promotion that expired 40 days ago (its Jinja page stayed; the contract dropped it) and a
  reviewed Jinja guide, and crawls every page, sitemap URL and `_redirects` source of the old
  site: all resolve (skipped when `web/node_modules` is missing). On the real data the live
  sitemap's 363 URLs resolve on the real-data build (below). During the phase-2 week a daily
  Actions workflow (`crawl.yml`, 07:30 UTC) runs `site crawl` on the live site against the Jinja
  sitemap saved before the cutover (`docs/cutover/jinja-sitemap-2026-10-14.xml`); it goes with
  the Jinja code. The tests keep building the Jinja sitemap from the same database (it follows the
  data); the committed snapshot is for the live crawl only: it is the exact list search engines had
  on the day of the switch, and the daily job needs no database.
- **Real-data check (2026-10-14, a read-only copy of the database after run 33, nothing
  deployed):** export (no new links) 360 routes, 6 origins, 156 destinations, 0 promotions (none
  approved yet), 7 low prices. `site build`: **627 HTML pages** (360 route, 157 destination hubs
  + index, 7 origin + index, 96 ponte, home, explorer, `/roteiros/`, `/dicas/`, About, Privacy,
  404), `sitemap.xml` 528 URLs, 2 redirects (`/guias/voos-baratos-dicas` ±slash → `/dicas/`, the
  tip still a draft); **17.6 s with `npm ci`, 7.8 s without**; `web/dist` 31.2 MB in 644 files
  (route pages ~50–60 KB each with inlined CSS and logo). A rebuild with a newer export gave the
  same deploy hash (would be skipped). The live sitemap (https://pontonomada.pt/sitemap.xml, 363
  URLs) and the Jinja build's: all 363 resolve on that build (`site crawl --dist`).
  **Lighthouse** (`lhci` with a temporary config on the real build, mobile, median of 3;
  performance / accessibility / best practices / SEO): home 0.95/1/1/1, route
  `/voos/lisboa-londres/` 0.93/1/1/1, origin `/partidas/lisboa/` 0.93/1/1/1, hub
  `/destinos/londres/` 0.93/1/1/1, explorer 0.92/**0.96**/1/1, ponte
  `/pontes/1-dezembro-2026/porto/` 0.95/1/1/1; CLS 0 everywhere, FCP 2.4–2.7 s. The explorer's
  0.96 was `target-size`: with six origins its ponte links wrapped onto two rows with no gap
  (the fixtures have three). **Fixed (code review, 2026-10-14):** each origin link is an
  `inline-flex` target of at least 24 × 24 px (`min-h-6 min-w-6`) and wrapped rows get
  `gap-y-xs` (WCAG 2.5.8; a test checks the classes); re-measured on a fresh real-data build
  (same copy of the database, 627 pages): home 0.95, route 0.93, origin 0.93, hub 0.93,
  explorer 0.92, ponte 0.95 performance, and **1 / 1 / 1 accessibility / best practices / SEO on
  all six** (assertion: accessibility = 1); the fixture `npm run lhci` (12 URLs) passes too. No promotion page could be measured (none in the
  real data); the fixture runs of D28/D34 cover them, and the slide-strip CLS flake noted in D28
  is to be checked on the first real promotion.
- **Phase 2 (done 2026-10-21):** the `crawl` workflow ran daily from 2026-10-14 to 2026-10-20,
  every run "363 URLs: 363 ok (0 by a 301), 0 broken", and a local `site crawl --sitemap
  docs/cutover/jinja-sitemap-2026-10-14.xml` on 2026-10-21 gave the same. Deleted:
  `SiteBuilder`/`build_site` and their page dataclasses, `website/templates/`, `site
  build-jinja`, `.github/workflows/crawl.yml`, and what only the Jinja pages used
  (`presentation.LowPriceView`/`build_low_price_view`, `pipeline.shown_low_prices`/
  `route_low_prices`, config `site.low_prices_per_route` and `site.recent_expired`,
  `Context.site_dir`); the Astro route page's cap is `LOW_PRICES_PER_ROUTE` in
  `web/src/lib/routes.ts`. The Jinja-page tests went; their checks now run on the export:
  website and low-price links, a failed link retried (`test_brand_switch.py`,
  `test_website.py`, `test_site_data.py`), the slides a runner downloads (`test_actions.py`);
  `test_traceability.py` keeps the checker, the captions and the scenario (the Astro pages are
  traced against the export by `web/test/traceability.test.ts`, the export against the
  database by `test_site_data.py`). `test_crawl.py` no longer builds the Jinja site: it seeds
  the redirect history the Jinja builds left (`site.paths`) and crawls, on the real Astro
  build, the committed sitemap's URLs of the test database's routes and static pages plus an
  expired promotion, its short alias and a Jinja guide; another test checks the committed
  sitemap itself (363 URLs, static pages and `/voos/<slug>/` only). Crawling the whole
  committed sitemap on a test build is not possible: its 360 routes are the live database's.
  The slug helpers stay in `website/__init__.py` (moving them was not worth the churn), as do
  `images.py`, `routing.py`, `redirects.py`, `deploy.py`, `crawl.py`; the committed sitemap
  stays as the list of old URLs the redirects must keep serving (`site crawl` reads it).

## D36: Instagram publisher (2026-10-14, #24)
- **Media: JPEG slides on the public site.** Meta's content publishing API fetches images by URL
  and takes JPEG only, so `site build` writes every slide twice into `web/dist/img/promos/<id>/`:
  `slide_NN.webp` (what the pages show, D35) and `slide_NN.jpg` (quality 90, progressive, the
  slide's own 1080 × 1350). The JPEG paths come from `website.deal_jpeg_paths` (next to
  `deal_image_paths`, the one place for image paths); they are not in the contract, since no page
  shows them. Approved promotions are public (`website.is_public`), so an approval's next full
  path (which the approval itself triggers, D26) builds and deploys its JPEGs; the publisher
  never posts before they answer (below). ~5 slides × ~250 KB per promotion: well inside Pages'
  limits.
- **API: Instagram API with Instagram Login** (`graph.instagram.com`): no Facebook Page needed,
  the token belongs to the professional account, permissions `instagram_business_basic` (list
  the account's posts, for the duplicate check) and `instagram_business_content_publish`. The
  host comes from one map (`config.GRAPH_HOSTS`, read through `InstagramConfig.host`, keyed by
  `instagram.login`) and the version from `instagram.api_version` (`v23.0`); `Graph(http, api,
  token)` and `ensure_token(secret, api, …)` take the config itself, not loose host/version/
  refresh parameters. Facebook Login (`graph.facebook.com`, the account linked to a Page) is
  `login: facebook`: same endpoints and ids, and **no refresh**, so it needs a Page token that
  never expires (from a long-lived user token; the runbook says how); a 190 from Meta there is
  handled like any refused token (below). Secrets `INSTAGRAM_ACCESS_TOKEN`,
  `INSTAGRAM_ACCOUNT_ID` (`Secrets`, optional; `.env.example`, the workflow's env, `test_workflow`
  checks every `Secrets` field comes from Actions secrets). `posting.publishers.instagram:
  instagram` in config. **Without both secrets the channel is `instagram.Paused`**: due posts
  wait ("À espera do token: faltam …", no attempt counted, shown by `queue list` and the run
  log), expiry and rejection still cancel them. Not the dry run: that settles the post
  `published`, and the promotion would have lost its Instagram slot for good (code review).
  Setup for Miguel: `docs/runbooks/instagram.md` (pt-PT).
- **Publisher protocol (posting.py), extended:** `publish` may raise `PublishWait` (stays queued,
  **no attempt counted**, the reason in `last_error`) or `PublishCancel` (cancelled with the
  reason); any other exception is a failure counted against D32's `max_attempts`.
  `posting.attempt` turns a call into data (result / wait / cancel / error) so the post and the
  story ladders in `run_publish` read the same. `Published` gained `marks_published` (`run_publish`
  then calls `pipeline.mark_published`, the same writer as `deal published`, with actor
  `posting.publisher_actor(name)` = `instagram-publisher`: review event v1's `actor` is free text,
  so its schema is unchanged) and `story` (a story follows, `posting.StoryPublisher`, a
  runtime-checkable Protocol with `publish_story`). Story states are `posting.StoryStatus`
  (`pending`, `published`, `skipped`; the SQL CHECK is tested against it, like `CHANNELS`). The
  factory moved to `pipeline.publishers_for` (it needs the database and the object store for the
  token); `posting.publishers` is gone.
- **Flow** (`instagram.InstagramPublisher`, called by `run_publish` after D32's verdict, so only
  a due post whose price was verified within 6 h): (0) the caption: the one stored on the row at
  the first attempt (`posting_queue.caption`), else the rendered one, stored now; (1) HEAD every
  JPEG URL (`website.public_jpeg_urls` = `site.base_url` + `deal_jpeg_paths`; redirects followed,
  but the final URL must be https and answer 200, `instagram.image_problem`): otherwise wait ("As
  imagens ainda não estão no site …: espera pelo próximo deploy"), the normal case when an
  approval's slot comes before the full path deployed (the publish step runs before the path
  decision). **Bounded:** more than `instagram.images_wait_hours` (24) after the slot, each such
  run is a failure ("As imagens continuam sem estar no site mais de 24 h depois da hora
  marcada …"), so `max_attempts` cancels a post whose images never arrive (a broken deploy);
  (2) `content_publishing_limit`: fewer than 2 left (carousel + story) → wait; (3) the account's
  25 latest posts: one whose caption matches the stored caption (line by line, blank lines and
  outer spaces ignored) is this carousel already published by a run that died before recording
  it → adopted, never posted again; (4) one container per slide (`is_carousel_item`, at most 10;
  a single slide is a plain image post), **every child polled to FINISHED** (together, same
  backoff; one in ERROR/EXPIRED is a failure and the next attempt makes new children; still in
  progress → wait), then the CAROUSEL container with the caption; (5) its status polled
  (`status_code`) right away and after 2, 3, 5, 10, 15, 25 s (~1 min, injected sleeper):
  FINISHED → on; ERROR/EXPIRED → the container is forgotten and it is a failure (a new one next
  time); still IN_PROGRESS → wait, the container kept for the next run; (6) `media_publish`;
  (7) the permalink (failing to read it leaves the URL empty, the post is out). The resume of a
  kept container (`_reuse`: PUBLISHED / broken / go on) and its finish (`_finish`: poll,
  `media_publish`, record) are one code path for the carousel and the story. Then `run_publish`
  writes the `published` decision (`post_url` = permalink; without R2 it is applied at once, with
  R2 by the next run; a failure to write it is logged, never fails a post that is out), settles
  the row `published` (publisher `instagram`, `result_url`) and marks its story pending.
- **Story**, right after in the same run (`pipeline._run_stories`, every run for pending
  stories): a STORIES container of the cover JPEG (limit: 1 left), polled and published the same
  way. Its failure never touches the carousel: `story_attempts` count up to `max_attempts`, then
  `skipped`; `posting.story_verdict` (pure) skips it once the promotion expired or was rejected
  or 6 h (`max_check_age_hours`) passed since the carousel, since the cover shows a price.
- **Idempotency, schema v11** (`SCHEMA_VERSION` 11; `schema.sql`; migration 11 = eight `ALTER
  TABLE posting_queue ADD COLUMN`; the upgrade tested from the real v5/v7 schemas and from a v10
  database with a queued row): `container_id`, `media_id`, `story_status` (`StoryStatus`,
  CHECK), `story_container_id`, `story_media_id`, `story_attempts`, `story_note`, `caption`
  (added to v11 in code review; v11 never reached a released database). Each id is committed
  the moment Meta returns it (`db.save_post_progress`); a retry resumes from it (a stored
  `media_id` skips straight to the permalink; a stored container is reused unless
  ERROR/EXPIRED; a container that says PUBLISHED but whose post is not among the latest is
  cancelled with "confirma no Instagram", never republished). The caption check covers the case
  the database can't: a job killed after `media_publish` and before the push (D21), whose ids
  never reached R2. It compares the **first attempt's caption**, kept on the row, so a caption
  that renders differently later (a new photo credit, a hashtag) can't make a retry miss the
  carousel and post a second one (tested); the carousel itself is posted with that caption too.
  Only a killed job loses that stored caption with the rest; then the freshly rendered caption
  is compared, which is the same unless the text changed in between.
- **Errors** (`instagram.classify`, Meta's error reference): code 190/102 (token) **on any call**
  (container, status, publish, story, limit, refresh; with either login) → wait, no attempt
  counted, a pt-PT line in the run log and meta `instagram.token.problem` shown by `queue list`
  until a later call gets through (`instagram.token_state`, cleared by a successful post or
  refresh, or by a new secret); 4, 17, 32, 613, 80002 and subcode 2207042 (rate and publishing
  limits) → wait; 10 and 200–299 (permissions) → wait with the runbook; subcodes
  2207004/2207005/2207009/2207023/2207028 (image too large, format, aspect ratio, media type,
  carousel size) → cancel with a pt-PT reason; anything else (5xx, transient, unknown) →
  failure, retried. The list is to be checked against the first real errors. Messages never
  carry the token: `Graph` sends it as the `access_token` parameter and replaces it in any
  error text; transport errors are reported by type only (their text can hold the URL).
- **Token refresh** (`instagram.ensure_token`, every run with the secrets, before publishing, so
  a quiet week can't let it lapse): long-lived tokens last 60 days and can be refreshed once at
  least 24 h old (`GET graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token`,
  answering `access_token` + `expires_in`). Meta `instagram.token` keeps the token's fingerprint
  (sha256, 12 hex), `first_seen`, `expires_at` (from the refresh answer), `refreshed_at`,
  `secret_outdated`, `problem`, never the token. Refresh when fewer than `instagram.refresh_days`
  (10) remain; a token of unknown expiry (a new secret: Instagram Login has no debug endpoint
  without the app secret) is refreshed once a day old, which tells its expiry. An expiry in the
  past → nothing posted (`instagram.Paused`: every due post waits), "O token do Instagram expirou
  a …". **Where the new token goes:** CI can't write GitHub secrets, so a new token string is
  written to the object store at `private/instagram/token.json` (R2 with keys, else
  `data/objects/`; never the database, which has daily backups, nor a log) with the
  fingerprints it replaces; **later runs use it** while the secret is still one it replaced, so
  publishing never stops because the secret is stale, and refresh it again in turn. Miguel is
  told in the run log and by `queue list` ("Token do Instagram renovado a …: atualiza o secret
  INSTAGRAM_ACCESS_TOKEN …"); `escapadinha instagram token` prints it on the PC (refused when
  `CI` or `GITHUB_ACTIONS` is set); once the secret matches, the notice goes. Rejected: printing
  the token in the run (Actions logs are kept), a GitHub token able to write secrets (a far
  wider credential than the problem needs), the database (backed up daily, copied to the PC).
- **Site:** `promotions.json` gained `post_url` (additive in v1, optional in the schema so older
  exports validate; only an `https://(www.)instagram.com/` URL, the publisher's permalink or one
  given by hand with `deal published --url`, else null). The promotion page shows **Ver no
  Instagram** with it (`[data-post-link]`; tested on the configured fixture build, which marks
  the live promotion published with a fake URL). The committed fixtures got `"post_url": null` by
  hand instead of `export fixtures`: regenerating from today's database would replace every
  fixture value the web tests pin (the real data moved since), for a field that is null there.
- **Not done here:** the first real post, which needs Miguel's token (runbook §5); the issue
  stays open until he confirms it.

## D37: Affiliate blocks for eSIM, insurance and activities (2026-10-14, #18)
- **Programmes** (checked 2026-10-14 in Travelpayouts, website Project 585209, already
  connected, no application needed): **eSIM = Yesim** (`https://yesim.tech`, 18 %, 90-day
  cookie, web and app purchases tracked; Airalo pays 12 % and tracks mobile web only, while most
  eSIMs are bought in the app); **activities = Tiqets** (`https://tiqets.com`, 3.5–8 %, 30 days,
  strong on European museums and attractions; Klook is Asia-focused); **insurance = none**: EKTA,
  the only connected insurance programme, stopped bookings on 2026-10-08 and is disabled on
  2026-10-14, and the alternatives Travelpayouts suggests (VisitorsCoverage, Insubuy) are for the
  US market. The insurance block ships unconfigured.
- **Configuration, never code:** `affiliate.programmes` in config.yaml maps each block programme
  (`esim`, `insurance`, `activities`: `config.PROGRAMMES`, the only names in code, since each is a
  component with its own copy) to `ProgrammeConfig`: `brand` (named in the copy), `url` (the
  brand's own https page; a `marker=` URL is refused at load, D19) and optional `destinations`
  (city code → a deeper page on the brand's site, for an itinerary of that city; empty today: the
  partner links API converts any page of a connected brand, but no city page was chosen, and
  guessing Tiqets' city URLs, which carry ids, would be inventing them). `null` = not configured.
  Connecting insurance later is a config change only: brand + url, and the next run's
  fingerprint (config.yaml is in it) takes the full path.
- **Which articles get links:** the MDX front matter lists the blocks the body uses,
  `affiliates: [esim, activities]` (zod enum in `content.ts`; the spec's "affiliate blocks" field
  of the itinerary template). The pipeline reads only that front matter (`articles.py`,
  `published` = the D33 gate: `reviewed: true`, test-only entries only for fixture data) and
  never parses the body: a body block whose programme the front matter does not list **fails the
  build** (`affiliateBlock` throws), so the two can't silently disagree in the direction that
  loses a link. Listed but unused costs one stored link, nothing else. Drafts get no link (the
  site never builds them; in the dev server their blocks render nothing and warn).
- **One gate, two readers:** `articles.py` re-implements the site's gate, so both are checked on
  the same cases, `web/test/fixtures/content-gate-cases.json` (the `review-rules.json` pattern):
  each case is a front matter as YAML text with whether it is refused, built from real data,
  built from fixture data, its key and its programmes. `web/test/content.test.ts` parses it with
  Astro's own front matter parser (`@astrojs/internal-helpers/frontmatter`, js-yaml) and the zod
  schemas + `isVisible` + `articleKey`; `test_affiliate_blocks.py` with `articles.load` /
  `published`. Python matches zod: YAML 1.2 booleans (a SafeLoader without YAML 1.1's
  `yes`/`no`/`on`/`off`: PyYAML would read `reviewed: yes` as true, Astro as a string the schema
  refuses), `reviewed`/`fixture` must be booleans, `affiliates` a list of known programmes;
  anything else raises `ArticleError` (the export stops, as the site build would). The article
  key (`<collection>/<file name>`) is `content.articleKey` on the site (both pages) and
  `Article.key` in Python, pinned by the same cases.
- **Links:** which pairs get one is decided in one place, `pipeline.block_targets` (published
  article × listed programme that config configures → the programme's page for the article);
  `pipeline.article_links` creates one per pair through `PartnerLinksClient` for the **website**
  Project (falls back like D19), **sub_id per article** (`roteiro-<slug>`, `dica-<slug>`: the
  dashboard shows what each article earns; the brand already tells the programmes apart), and
  the fixture export puts its placeholders on the same pairs. Stored in meta `site.article_links`
  (Project → `<programme>:<collection>/<slug>` → target, url, error), like D25's `site.links`: CI
  keeps no files, and `partner_links` is keyed by observation (with a foreign key and a 30-day
  prune), which an article is not. Each link remembers the page it was made for, so a new page
  in config gets a new link. **Pruned on every write:** only the current website Project's
  entries for the current pairs are kept, so an article back to draft or deleted, a programme
  dropped from its front matter or from config, or a Project switch forgets the old links (one
  that comes back gets a fresh link). **One API request per article**:
  `PartnerLinksClient.create` keys results by url, so two articles' links for the same brand
  page can't share a request (their sub_ids differ); an article's own programmes are different
  brands (the real API echoes `https://yesim.tech` and `https://tiqets.com` exactly, checked
  with the website Project). No per-run budget like D24's low prices: links are created once,
  for hand-written articles (tens, not thousands). **Retry:** a failure is stored with its
  reason and left out of the export; links are only created by `export site-data`, which runs
  in the full path, so it is retried by the next full path, exactly like the website's deal
  links. A failed link alone does not trigger one: the fast path's fingerprint
  (`site_data_digest`, `create=False`) reads stored links only, and a missing link changes
  nothing there. `_partner_links` now delegates to the shared `_tracked_links(ctx, channel,
  [(url, sub_id)])`.
- **Contract:** new file `affiliates.json` (additive in v1, like D31's pontes:
  `meta.files.affiliates` optional, the loader defaults to no programmes and no links):
  `programmes` (all three, `{brand}` or null) and `links` (`{article, programme, url}`, sorted).
  The block disclosure is `labels.json` `disclosure.affiliate` (optional, next to `site` and
  `post`; `presentation.BLOCK_DISCLOSURE`, "Publicidade: esta ligação é um link de afiliado. Se
  comprares através dela, podemos receber uma comissão, sem custo extra para ti.": the site's
  disclosure speaks of booking buttons, a block is not one). No prices; nothing per-run, so
  `shown_digest` (the full path's fingerprint) covers it unchanged. Fixture data links each
  test-only and reviewed article to `https://example.com/parceiro/<sub_id>` without reading
  stored links, and **only the test-only ones** (2026-10-15, #19: publishing the real articles
  changed the fixture export): the committed `affiliates.json` depends on the test content, never
  on which real articles are approved. The gate itself is unchanged (`articles.published`, the
  shared cases); in a fixture build a real article's blocks render nothing, with the build's
  warning, and the web tests check the warnings of the test itinerary only. The committed fixtures got `affiliates.json`, `meta.files.affiliates` and
  `disclosure.affiliate` **by hand** (D36's reason: regenerating would move every pinned value);
  `test_affiliate_blocks.py` checks the committed `affiliates.json` and the whole `labels.json`
  equal what `build_export(fixture=True)` writes for the repo's config and fixture content.
- **Site:** `<EsimBlock />`, `<InsuranceBlock />`, `<ActivitiesBlock />` (thin wrappers of
  `AffiliateBlock.astro`), passed by the itinerary and tip pages to `<Content components>`
  (`src/components/mdx-components.ts`), so authors write the tag without an import. MDX gives a
  component no way to know its article, so the page sets `Astro.locals.article` (`{key,
  affiliates}`; Astro shares one `locals` object across a page's render) before rendering the
  body; a block outside an article fails the build. `src/lib/affiliates.ts` `affiliateBlock`
  decides: programme not configured or no link yet → no block and a `console.warn` in the build
  log (`[affiliates] itineraries/x: insurance block not shown: no programme configured …`);
  otherwise the pt-PT copy (`BLOCK_COPY`, brand from the contract; feminine article, "da Yesim",
  "na Tiqets", as brands are in pt-PT), the link through `cta.partnerLink` (the booking buttons'
  https check and `CTA_REL`, `rel="sponsored nofollow noopener"`), `target="_blank"`, and the
  disclosure (a block without one throws), always in the same `<aside data-affiliate>` (tokens
  only). The test itinerary uses all three blocks; the fixture build shows eSIM and activities
  and no insurance, with the warning (both builds' logs are now handed to the tests); the
  configured build gives insurance a fake brand and link and shows it, and drops the activities
  link: configured but not created yet, nothing rendered and a warning.
- **Astro content cache:** `node_modules/.astro/data-store.json` is invalidated only when the text
  of `src/content.config.ts` changes, not `src/lib/content.ts` (found here: entries cached before
  `affiliates` existed came back without it). Every build now runs `astro build --force`, which
  clears that cache: `npm run build` (the pipeline's `site build`), `build:fixtures` and the web
  tests' builds (`test/build-site.ts`); `test_web_build.py` checks all three. A full re-read of
  the few MDX files costs nothing measurable.
- **Not done here:** an insurance programme (none usable for Portuguese residents yet); city
  pages in `destinations` (Miguel can add them, after checking the brand's URL); block usages in
  real articles: there is no itinerary draft in `web/src/content/itineraries/` yet (#19 writes
  them, with the blocks where they fit).

## D38: Telegram channel publisher (2026-10-15, #21)
- **What goes out:** for each approved promotion, one **photo message** in the public channel
  (`TELEGRAM_CHANNEL`), sent by a bot that is an admin of the channel allowed to post
  (`TELEGRAM_BOT_TOKEN`). Bot API `sendPhoto` (`https://api.telegram.org/bot<token>/sendPhoto`,
  the host only in `config.TELEGRAM_API`), form fields `chat_id` (= `TELEGRAM_CHANNEL`), `photo`
  (a URL Telegram fetches) and `caption`. Config `posting.publishers.telegram: telegram`;
  `PublisherName` gained `telegram` and the validator now says a real publisher (anything but
  `dry-run`) posts only to its own channel. **The channel secret is checked by the publisher
  factory** (`telegram.channel_problem`): an @handle (a Telegram username: 5–32 letters, digits
  or `_`, starting with a letter) or a numeric id; no guessing (`pontonomada`, a t.me link are
  refused). A malformed one **pauses Telegram** like a missing secret: due posts wait (no
  attempt counted, nothing sent) with "TELEGRAM_CHANNEL tem de ser o @handle do canal público …"
  as their reason, in the run log and as a `queue list` notice. Code review: a first version
  validated it when `Secrets` load, which stopped the whole run (collection, detection, the
  site) over an optional channel's typo; tested now that a run with a bad channel still
  collects and its Telegram post waits.
- **When:** D32 queues Telegram at the approval's application ("immediately") and that stays; the
  photo, though, is the cover slide's JPEG on the public site (`website.public_jpeg_urls(…)[0]`,
  the image D36 already deploys for Meta, so one image path serves both), and the publish step
  runs before the full path that deploys it. So the run that applies an approval finds the
  image missing and **waits** (no attempt counted), and the next run (≤ 2 h) sends it. Bounded
  like Instagram's: more than `telegram.images_wait_hours` (24) after the post was due, each
  such run is a failure, so `max_attempts` ends a post whose image never arrives. Rejected for
  now: uploading the rendered slide (multipart) to post in the approval's own run (a runner
  would download it from the output mirror, and two image paths would drift); a second publish
  step after the deploy (changes `run`'s order for one channel). Either can come later if 2 h
  matters.
- **One image check for both publishers:** the HEAD check moved from `instagram.image_problem`
  to `website.image_problem` (next to `public_jpeg_urls`: 200 required, redirects followed,
  https only) and the bounded wait to `posting.live_images(urls, check, due_at, now, wait)`
  (pure, the check injected; "As imagens ainda não estão no site … / continuam sem estar no site
  mais de 24 h depois da hora marcada"). Its failure is `posting.RetryableSendError`, the
  queue's "retried, attempt counted" signal by name (Instagram's `InstagramError` is one). The
  token redaction is one helper too (`posting.redact`, used by `instagram.Graph` and
  `telegram.BotApi`), and `instagram.Paused` builds on the new generic `posting.Paused`.
- **Text:** the post's `Message.text`, i.e. `captions.whatsapp_text` (D32: headline with the
  arrival airport, price, dates, found/checked times, the stored partner link and `DISCLOSURE`),
  plain text (no `parse_mode`, so nothing needs escaping; Telegram links the URL itself).
  Telegram's photo caption limit is 1024 characters counted in UTF-16 code units (an emoji is
  2): a longer text is **cancelled** with the reason, never cut, since cutting could drop the
  link or the disclosure. Today's texts are about 450.
- **Not "published":** the message returns `Published(url, marks_published=False)`. Instagram is
  the promotion's main channel (D36); a `published` promotion cancels its queued Instagram post
  (D32), and Telegram usually goes first. Its message id is stored on the row (`message_id`,
  schema v12: `SCHEMA_VERSION` 12, `schema.sql`, migration 12 = one `ALTER TABLE posting_queue
  ADD COLUMN message_id TEXT`; the upgrade tested from the real v5/v7 schemas and from a v11
  database with a published row) and its link (`https://t.me/<chat.username>/<message_id>`,
  from the answer's chat; none for a channel without a username) in `result_url`. **Where the
  link shows:** `queue list` (every queued post of the promotion lists the links of its posts
  already out: "Instagram deal 12 … · agendada · Telegram: https://t.me/…"), `queue list --all`
  (the row itself) and `deal check` (after the price, each channel's post: when it goes out, or
  how it went, with its link). Not on the promotion page: `post_url` is the Instagram permalink
  (contract v1, D36); a Telegram link there would need a contract field and is not asked for.
- **Never twice: a send record in the object store.** Telegram lets a bot neither list a
  channel's messages nor send with an idempotency key, so there is no Instagram-style "find the
  post by its caption". Instead, before the request, `posting/telegram/deal-<id>.json` (deal,
  observation, post, chat, `started_at`) is written to the object store, which is durable at
  once (R2, or `data/objects/`), unlike the database, which reaches R2 only at the end of the
  run (D21); after Telegram's answer the record gets `message_id`, `url`, `sent_at`, and the row
  `message_id`. Then:
  - Telegram **refused** (`ok: false`, any status) or the request **never reached it**
    (`ConnectError`, `ConnectTimeout`, `PoolTimeout`): nothing went out; the record is removed
    and the error classified (below).
  - **The answer was lost** (read timeout, protocol error, an answer that isn't the API's JSON,
    e.g. a proxy's 502/504 page): the message may be in the channel. The post is **cancelled**:
    "O Telegram não respondeu ao envio (…): a mensagem pode ter saído. Confirma no canal …: não
    é reenviada sozinha, para não sair repetida; se não saiu, `escapadinha queue retry <deal>
    telegram` volta a pô-la na fila." The record stays.
  - A later run finds a **record with a message id** (the run that sent it died before its
    database reached R2): the message is adopted (row `message_id`, `result_url`, settled
    `published`), not sent again. A **record without one** (the run died between the request and
    the answer): cancelled the same way, "Uma tentativa anterior (…) enviou a mensagem … sem
    guardar a resposta". A record whose observation differs from the deal's (a deal id reused
    after a lost database) is ignored.

  **The trade-off: at most once, with a way back.** A lost answer never resends by itself; a
  duplicate in a public channel would cost more, and a bot can't see the channel to tell.
  `queue list` lists every such send ("Envio ao Telegram por confirmar: deal N (…). Confirma no
  canal …", `telegram.unconfirmed`: records without a message id or a retry request) until
  Miguel acts. Having checked the channel and not found it, **`escapadinha queue retry <deal>
  telegram`** (`pipeline.retry_post`) puts it back: refused, with the reason, for another
  channel, a promotion no longer approved, no record ("não há nenhum envio ao Telegram por
  confirmar") or a record with a message id ("a mensagem do Telegram saiu (link): não há nada a
  repor"). Like a review decision (D26) the request is written to the store (the record gains
  `retry_requested_at`) and applied by the code that owns the database
  (`telegram.apply_retries`, first thing in `run_publish`; without R2 at once, so the CLI says
  "voltou à fila e sai na próxima execução"): a cancelled Telegram row whose reason names the
  retry command is queued again (`db.requeue_post`: attempts reset, its due time kept, so due
  now), and the send no longer stops at that record; any other cancellation (an expiry after
  the request) stands, and the request is idempotent (a lost database just requeues again).
  Rejected: retrying after a timeout (duplicates); `getUpdates` to see the bot's own channel
  posts (bots get no updates for their own messages, and a webhook or another consumer would
  take them); a database-only marker (lost with the database by a killed job, the very case it
  is for); the CLI writing the queue row itself (with R2 the run's database would overwrite it).
- **Errors** (`TelegramPublisher._signal`). The texts are the Bot API's: its own (source:
  tdlib/telegram-bot-api `telegram-bot-api/Client.cpp`, `Client::fail_query_with_error`, which
  maps WEBPAGE_CURL_FAILED → "Failed to get HTTP URL content", WEBPAGE_MEDIA_EMPTY → "Wrong type
  of the web page content", WC_CONVERT_URL_INVALID/EXTERNAL_URL_INVALID → "Wrong HTTP URL
  specified", "File generation failed" → "can't upload file by URL", prefixes "Bad Request:" /
  "Forbidden:" and turns an all-caps 403 into a 400) or MTProto error names passed through
  ("Bad Request: CHAT_WRITE_FORBIDDEN"; names and meanings from
  core.telegram.org/method/messages.sendMedia). The chat texts ("chat not found", "bot is not a
  member of the channel chat", "need administrator rights in the channel chat", "not enough
  rights to send photos to the chat", "bot was kicked from the channel chat") and "wrong file
  identifier/HTTP URL specified", "message caption is too long" are the Bot API's well-known
  answers elsewhere in that file, not re-verified line by line. Matched case-insensitively:
  - 429 → wait ("Limite de mensagens do Telegram (tenta daqui a N s) …", from
    `parameters.retry_after`), no attempt counted;
  - 401 (the token) and **a refused channel** (any 403; a 400 matching `CHANNEL_SETUP`: chat not
    found, not a member, kicked, not enough rights, need administrator rights,
    CHAT_WRITE_FORBIDDEN, CHAT_ADMIN_REQUIRED, CHAT_RESTRICTED, CHAT_SEND_PHOTOS/MEDIA_FORBIDDEN,
    CHANNEL_PRIVATE, CHANNEL_INVALID, PEER_ID_INVALID, USER_BANNED_IN_CHANNEL) → **wait**, no
    attempt counted, with a notice in meta `telegram.problem` ("O Telegram recusou o canal (…):
    confirma que o canal … existe e que o bot é administrador com permissão para publicar …;
    as publicações esperam."), shown by `queue list` until a message goes out. Code review: a
    first version cancelled here, so one setup mistake lost every approved promotion's post;
    now they wait for the fix (an expiry still cancels them, D32);
  - this message refused for good (`PERMANENT`: PHOTO_INVALID_DIMENSIONS, PHOTO_EXT_INVALID,
    IMAGE_PROCESS_FAILED, "wrong HTTP URL specified", MEDIA_CAPTION_TOO_LONG, "caption is too
    long") → **cancel** with "O Telegram recusou esta mensagem: <pt-PT why> (…)", no notice;
  - a photo Telegram couldn't fetch now (`TRANSIENT_PHOTO`: "failed to get HTTP URL content",
    "wrong type of the web page content", "wrong file identifier/HTTP URL specified",
    PHOTO_SAVE_FILE_INVALID ("Internal issues, try again later"), "can't upload file by URL")
    → failure, retried (the HEAD said it was live);
  - anything else (another 400, 5xx with the API's JSON) → failure, retried up to
    `posting.max_attempts` (5). The lists are to be checked against the first real errors.
- **The token** is part of the URL path. `BotApi` reports transport errors by type only (their
  text can hold the URL) with `raise … from None`, replaces the token in any text Telegram sends
  back (`posting.redact`), and never logs; it isn't stored anywhere but `.env` and the Actions
  secret (tested: logs, reasons, the whole database and every object in the store). httpx logs
  request URLs at INFO level; the pipeline configures no logging (so only warnings print), and
  must not turn INFO on for httpx.
- **One publisher registry:** `pipeline.PUBLISHERS` maps each publisher name to a
  `PublisherKind` (`build(PublisherSetup)`: the run's context, database, HTTP client, clock, log
  and sleeper; `notices(ctx, conn)` for `queue list`); `publishers_for` and
  `publisher_notices` read only it, and a test checks config's `PublisherName` against it. A new
  channel is a module, a registry entry and the name in `posting.CHANNELS`/`PublisherName`.
- **Without the secrets** the channel is `posting.Paused("telegram", …)`: due posts wait ("À
  espera do bot: faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHANNEL …"), never settled by the dry
  run, which would lose them (D36). Secrets in `Secrets` (`telegram_bot_token`,
  `telegram_channel`, `telegram_configured`), `.env.example` and the workflow's env
  (`test_workflow`). Tests: the Bot API and the site mocked with respx (`tests/test_telegram.py`);
  test_posting and test_instagram put Telegram on the dry run (their subject is the queue and
  Instagram).
- **Not done here:** the first real message, which needs Miguel's bot and channel
  (`docs/runbooks/telegram.md` §5); the issue stays open until he confirms it.

## D39: Nonstop fares from the cache on nonstop-only routes (2026-10-15, #41)
- **The change:** a route that takes only nonstop flights both ways asks
  `aviasales/v3/prices_for_dates` with `direct=true`; any other route keeps the plain call. Same
  request count per run (1080 today). Recommendation 1 of
  `docs/research/2026-10-15-data-reliability.md`.
- **Why:** the cache returns one offer per (departure, return) pair, the cheapest. When that offer
  has a stop, the pair's nonstop fare never reaches us, and a nonstop-only route throws the offer
  away. 57 % of the rows stored on these routes (2165 of 3790) were discarded for a stop. In one
  call, LIS-PAR December went from 8 to 21 nonstop trips over the same 26 pairs (the nonstop
  fare 3–45 € dearer than the one with a stop). LIS-ROM December gave 13 nonstop trips, 10 of
  them not in the database. The evidence rests on two route-months; the first run with the
  change gives the real number.
- **Which routes:** `RouteRules.nonstop_only` = `direct_only` **or** `max_transfers == 0`. Both
  discard every offer with a stop (`RouteRules.allows`), and `pt.stops_rule` already reads them
  as "só diretos". The issue says "direct_only"; a route overridden to `max_transfers: 0` is the
  same case, so it asks the same way. Today that is every `europe` and `domestic` route (320 of
  360); `long_haul` (`max_transfers: 1`) keeps `direct=false` by omission (today's call).
- **One query, from the rules:** `collector.travelpayouts.request_params(origin, destination,
  month, rules, …)` builds it, and the rules are passed in, never a global (like the detector).
  `PriceSource.fetch` takes the route's `rules=` in place of `min_nights`/`max_nights`, so the
  collection (`runner.collect`), `pipeline.price_now` / `live_check` and the review snapshot's
  `live_check.query` all ask the same. That is what stops the false expiries: the recheck reads
  the run's prices, and a deal's nonstop fare no longer drops out of them as soon as a cheaper
  fare with a stop appears for those dates ("a viagem já não aparece …"). If the live check kept
  the plain call, it would refuse approvals the recheck accepts.
- **The review Function (D26, D29)** sends the snapshot's query as is, so it gets `direct=true`
  with no code change. Contract v1 stays: `live_check.query` already allowed extra string or
  integer values, and `direct` is the string `"true"` (like `one_way: "false"`; a JSON boolean
  would break the schema). Only the schema's description changed.
  `contract/review/v1/fixtures/live-check-cases.json` gained `queries`: route rules → the exact
  query. `tests/test_live_check_cases.py` checks `request_params` against it, and
  `web/test/review/live-check.test.ts` checks that `liveCheck` sends exactly that on the wire.
  `tests/test_review_events.py` checks that the collection's request, the approval's live
  check and the snapshot query are one query.
- **Observation model unchanged:** the `direct=true` items have the same shape (link with
  `search_date`, airline, flight number, airports, stop counts), `parse_response` is untouched,
  and every row still comes from a payload. The flag is not trusted: `RouteRules.allows` still
  drops any item with a stop. The run archive keeps each request's `params`, so a run says
  which way it asked; older runs lack `direct`.
- **Expected effects:** 2–3× the usable rows on direct-only routes, and the first run backfills
  about 7 found days on busy route-months. A daily low is the minimum over more nonstop rows, so
  a typical low can only fall or stay: discounts get smaller, never inflated. Stored rows with a
  stop stay in the database (never deleted, never usable on these routes).
- **Rejected:** both calls per route-month (doubles requests for rows we discard); a separate
  `direct` field in the snapshot (the query already carries it, and the Function must not
  rebuild the query); changing only the collection (the live check would disagree with the
  recheck).

## D40: Promotions wait for a mature typical low; the reviewer sees the baseline (2026-10-15, #42)
- **Why:** the data-reliability research (`docs/research/2026-10-15-data-reliability.md`,
  recommendations 2 and 3). With 4–6-day baselines, 7 of the first 11 deals were not 30 % below
  the typical low once more days were known, and every discount fell (by 7 points in the
  median): the selection effect of small samples, where a deal fires when a thin baseline
  happens to be high. 45 % of baseline days saw a single departure date, and those days are a
  high outlier (above 1.25× the month's median) 24 % of the time, against 8 %.
- **Rules** (config `detector`, `DetectorConfig`, passed into the pure detector like the rest):
  - **A daily low counts** only if that day's usable offers for the route-month (within the
    route's rules) have at least `min_dates_per_day` (2) different departure dates.
  - **Low prices and every typical low the site shows** (route pages' months, the low-price rows'
    `typical`, the explorer) need `min_baseline_days` (7, was 4) counted days: `is_mature`.
  - **Promotion candidates** need `min_baseline_days_promo` (10) counted days whose first and last
    are at least `min_baseline_span_days` (9) days apart: `is_mature_for_promotions`. Until then
    only a route's `price_cap_eur` makes a candidate (D3, unchanged); `detect` shows "warming up"
    with days/10 and the span.
  - Unchanged: `threshold` 0.30, `min_saving_eur` 15, `low_threshold` 0.15, the median, the
    90-day lookback, the freshness window. `min_baseline_days_promo ≥ min_baseline_days` is
    enforced, so the tiers still nest (every candidate is also a low price).
  - **The span is a guard, redundant at the defaults:** 10 different days always span at least 9.
    It stays a setting of its own (the research's weekday/weekend cycle) so lowering the day count
    can't drop it. No minimum of observations (two dates a day already means two rows a day) and
    no outlier trimming (the median resists one bad day, the dates rule removes most of them).
- **Replay** (read-only copy of `data/escapadinha.db`: `mode=ro`, copied into memory, migrated
  there; runs 19–57 as in the research, offers present at run r = rows with
  `run_id ≤ r ≤ last_run_id`; the script and its output are in the PR):

  | Rule | Candidates, runs 19–57 | Low prices at run 57 | Route-months mature for promotions |
  |---|---|---|---|
  | Before (4 days, every day counts) | 8 (3 hold ≥ 30 % against today's median, 7 ≥ 20 %) | 32 on 10 routes | 30 |
  | 7 days, every day counts | 0 | 5 on 2 routes (LIS-BCN, OPO-PAR) | 4 |
  | **D40** (2 dates a day; 7 / 10 spanning 9) | **0** | **0** | **0** (7 have ≥ 5 counted days) |

  The "before" rows reproduce the research (276 route-months with usable rows, 217 with a
  baseline day, 30 / 15 / 4 at ≥ 4 / 5 / 7 days; one-date days 161 of 356). Up to run 58, the same.
- **Cost (agreed in #42):** no promotions and, today, no low prices either (the research's "5 on
  2 routes" was the 7-day rule without the dates filter). Route pages say "ainda sem dados
  suficientes" until a month has 7 counted days. Busy route-months should qualify from about
  20–25 October, sooner with the nonstop fares of #41. The 6 deals waiting for review were
  detected under the old rules; the queue's re-evaluation (below) expires them (replayed on run 58).
  **Known temporary effect (review of M1, 2026-10-16):** a ponte page (D31) is `noindex`, and so
  out of the sitemap (D34), while it lists no low price; with none anywhere, every upcoming ponte
  page leaves the index until its origin's route-months mature, then comes back on the next full
  path. Left as is: an indexed page that says "no prices" is the thin page D31 keeps out of
  search, and the sitemap is generated from the built pages, so nothing else needs undoing.
- **The queue against today's typical low (review of M1, 2026-10-16).** A deal waiting for review
  (`new`, `rendered`: `db.AWAITING_REVIEW`) stores the typical low it was detected on, and the
  site and the captions show that `baseline_median` once it is approved. The 6 deals in the queue
  were detected on 4–6-day typical lows, so approving one would publish an immature "habitual".
  So every run, right after detection, `pipeline.run_reevaluate` judges each of them again with
  the detector's own rule against its month's **current** typical low and the route's current
  rules (`recheck.promotion_expiry`, pure: `detector.evaluate` on the deal's price, the
  baselines passed in): a typical low mature for promotions, `threshold` and `min_saving_eur`
  below it; the route's `price_cap_eur` keeps only the deals it made (rule `price_cap`), and only
  while the month is not mature. A deal that would not be detected now **expires**, like a
  recheck's expiry (pipeline-owned, D26: never an approve or reject event; the recheck's time and
  price stay; `EXPIRADO.txt` in a rendered folder), with a pt-PT reason: "preço habitual ainda
  sem dados suficientes (5 de 10 dias)" or "já não é promoção face ao preço habitual atual
  (101 €): 80 € fica 21% abaixo; são precisos 30% e 15 €". **Approved deals are untouched**: a
  human approved them on the figures the review showed, and the price recheck still judges them.
  - **Replay** (read-only copy of `data/escapadinha.db`, `mode=ro`, copied into memory and
    migrated there; latest run 58): all 6 expire with "preço habitual ainda sem dados
    suficientes": deals 4 (LIS-BCN, 6 of 10 days), 5 and 7 (LIS-FNC, 5), 9 (OPO-FNC, 0: none of
    its days saw two departure dates), 10 (LIS-ROM, 2) and 11 (LIS-BER, 3). Their current typical
    lows are lower than the stored ones (LIS-BCN 64.5 € vs 76 €, LIS-FNC 69 € vs 102 €, LIS-BER
    113 € vs 134 €): against them only deal 10 (90 € vs 156.5 €, 2 days) would still be 30 % off.
  - **Known effects:** an expired deal's observation stays a deal (`deal_observation_ids`), so
    the same offer is never proposed again even once its month matures; a new price for the same
    trip still can be. A deal that survives keeps the figures it was detected with (the typical
    low it was judged against, as above); a deal detected before D40 survives only once its
    month is mature and it still passes against the new typical low, which the replay says none
    of today's 6 would do soon (only deal 10 is 30 % below, on 2 days, departing 27 October).
  - Rejected: refreshing the stored typical low of the survivors on every run (the rendered slides
    and caption would disagree with the database, and the reviewer's figures would move under
    them); judging approved deals too (that would overrule a human decision on data the human
    saw).
- **The reviewer sees the baseline:** "−39% vs. mínimo habitual 99 € (10 dias em 12, de 54 € a
  110 €)": 10 daily lows over a 12-day window (span + 1), the cheapest and the dearest of them.
  At detection a deal stores `baseline_span_days` and the observation ids of those two daily lows
  (`baseline_lowest_obs_id`, `baseline_highest_obs_id`; schema v13: `SCHEMA_VERSION` 13,
  `schema.sql`, migration 13 = three `ALTER TABLE deals ADD COLUMN`, tested through every
  migration from v1, and from the real old schemas `tests/fixtures/schema_v5.sql` and
  `schema_v7.sql` with a deal row, against a fresh install: column types, defaults and foreign
  keys of `deals`, the old deal kept with NULLs). Ids, not prices: the prices are read from those
  observations (`pipeline.baseline_range`), so they trace to `price_observations.id` (D2).
  Deals detected before keep NULLs: no range was stored, and recomputing one would mix in later
  days. Rejected: computing the range when the snapshot is made (it would drift from the typical
  low the deal was judged against).
- **Review snapshot (contract v1) and both review pages:** each deal gets `baseline: {span_days,
  lowest_eur, lowest_observation_id, highest_eur, highest_observation_id}` or null.
  **Versioning:** the contract's shapes change only with a new version; this is an optional
  field, added within v1 like D29's `transfers`, because no reader can break. Strictly, the deal
  object has `additionalProperties: false`, so a new snapshot **fails the pre-D40 schema**: v1
  can take the field only because the Function doesn't validate the snapshot at run time (an
  older Function ignores the key) and a newer Function reading an older snapshot (key absent)
  shows the days only, as for null. Review of M1 (2026-10-16): kept as the minimal honest option
  (a v2 would need a second snapshot or a lock-step deploy for no gain), with the condition made
  explicit in CLAUDE.md and held by a test (`web/test/review/page.test.ts`: a snapshot with keys
  the schema refuses still renders and still takes a decision). A reader that validates the
  snapshot would need a v2. Events are unchanged. New check:
  `tests/test_review_events.py::untraced_prices` traces every price of a snapshot (the deal's
  observation, its stored typical low, the recheck price backed by a stored observation, the
  baseline's two observations), and `SNAPSHOT_PRICES` fails on a new `*_eur` field in the schema
  until it is taught there. On both pages each extreme price sits in a `<span data-obs="<id>">`
  inside the card (`data-deal`; the local page's card gained it). Tests:
  `web/test/review/page.test.ts` (with the field, null, and absent; snapshots validated with ajv)
  and, for the local page drawn by its script, a browser test in `tests/test_review.py`.
- **Site contract v1:** `meta.detector.min_dates_per_day` (optional, added within v1). The route
  page explains "ainda sem dados suficientes" with it (`routes.typicalLowRule`: "…pelo menos 7
  dias de dados num mês, contando só os dias com preços para 2 ou mais datas de partida…"; an
  older export without it gets the old sentence). Typical lows follow the new maturity through
  `detector.is_mature`; nothing new changes per run, and `config.yaml` is already code in
  `run_path.fingerprint`, so the first run with these rules takes the full path and publishes
  the emptier pages. **Committed fixtures not regenerated:** `export fixtures` on today's
  database gives 0 low prices and almost no typical low, which would drop the low-price states
  the web tests build from. They stay as exported at run 30 under the old rules (still valid:
  the field is optional, and their meta without it is the pre-D40 case the site handles).
  Regenerate them once baselines mature. **Review of M1 (2026-10-16):** without the field the
  fixture build never drew the D40 sentence, so `fixtures/meta.json` `detector` got
  `min_dates_per_day: 2` and `min_baseline_days: 7` **by hand** (additive, the values a
  regeneration writes, as in D34 and D37); `web/test/route-pages.test.ts` checks the sentence
  and "1 de 7 dias". The months inside are still the run-30 export, so a few typical lows rest
  on 4–6 days under a meta that asks for 7 (test data, never deployed). The full regeneration
  waits for mature baselines: #52, which also adds a check that every fixture typical low has
  `min_baseline_days` days.
- **Tests:** detector (the dates rule, 10 days, the span, 7 days for low prices and the price-cap
  path, the extreme daily lows, the config's nesting); `run_detect` stores the range; the schema
  upgrade; the snapshot, the local page's JSON and card, the Function's card; the export (6
  counted days plus a one-date day: no typical low; 7: shown). Test histories now see two
  departure dates a day (`seed_history`, `test_traceability.history`, …), like real data.

## D41: A real 2-hourly schedule: a Cloudflare Worker dispatches the pipeline (2026-10-15, #43)
- **Why:** GitHub's `schedule` is best effort. The cron `17 */2 * * *` fired 9 times on
  10-14/15, 4.4–6.8 h apart (median 5.5 h; `docs/research/2026-10-15-data-reliability.md`,
  recommendation 5). The 2-hourly runs in the database came from the PC's Windows task, retired
  on 2026-10-15. The cadence stays 2 h: hourly would double the requests and the minutes for
  about 1.2× the usable offers per hour.
- **Trigger:** a Cloudflare Worker, `workers/scheduler/` (free plan). Its Cron Trigger
  `17 */2 * * *` (UTC, the old cron's minute) calls `POST https://api.github.com/repos/
  MiguelCorre/escapadinha/actions/workflows/pipeline.yml/dispatches` with `{"ref": "master",
  "inputs": {"full": "false"}}`: the workflow's only input, a routine run (`run_path` still
  decides fast or full, D25). Headers: `Authorization: Bearer <GITHUB_ACTIONS_TOKEN>`, `Accept:
  application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `User-Agent:
  pontonomada-scheduler`. Plain JavaScript (ES modules, `// @ts-check`), no npm dependency, no
  build step. `wrangler.toml` holds the cron, the vars (`GITHUB_REPOSITORY`, `WORKFLOW`, `REF`,
  `SKIP_IF_RUN_WITHIN_MINUTES`), `workers_dev = false` and `preview_urls = false` (no URL; there
  is no fetch handler), and Workers Logs (`observability`) for each tick's one line. Rejected:
  `repository_dispatch` (both of its types force the full path, D25); an external cron service
  (another account, another place for the token).
- **Token:** a fine-grained PAT for `MiguelCorre/escapadinha` only, with **Actions: Read and
  write** (dispatch, and read the workflow and its runs). It is stored only as the Worker secret
  `GITHUB_ACTIONS_TOKEN`: never a var, never in the repository, `.env` or the Actions secrets. It
  goes only into the Authorization header, and every log line and error message passes through
  `redact` (tested with the token echoed in GitHub's message, a network error's text and a run's
  fields). It is separate from the review Function's `GITHUB_DISPATCH_TOKEN` (Contents: write,
  for `repository_dispatch`, D29), so each token has only its own permission.
- **One tick, two windows** (`src/schedule.js` `tick`; pure, with fetch, clock and log injected):
  1. a workflow that isn't `active` (`gh workflow disable pipeline.yml`, the README's restore
     procedure) → skip;
  2. a `pipeline.yml` run **created** within the window, whatever its event, status or
     conclusion → skip, naming that run;
  3. otherwise → dispatch.

  The two reads are advice: if GitHub can't answer them, the tick dispatches anyway. A double run
  costs about 3 minutes, and the R2 lock and the `concurrency` group serialise it (D21, D25); a
  missed run costs 2 h of data. A refused or unanswered dispatch is logged with GitHub's status
  and message and throws, so Cloudflare records the invocation as failed.
- **No close double runs, and no gap.** `pipeline.yml` loses its `schedule`. GitHub's cron moves
  to a separate workflow, `pipeline-fallback.yml`, which only dispatches (with its own run's
  `GITHUB_TOKEN`, `permissions: actions: write`; `workflow_dispatch` is one of the events that
  token may start). So every run of `pipeline.yml` is a real run, which is what both windows
  count. Rejected: a skip gate inside `pipeline.yml`. A gated scheduled run still shows up as a
  successful run, so the Worker would count it and skip its own tick, which allows gaps of about
  4 h.
  - **Worker window: 45 min.** A run created in the last 45 min (a review decision's
    `repository_dispatch`, a manual run, the fallback) serves the tick. The longest gap a skip can
    leave is 45 + 120 = 165 min, below the 3 h warning, so a healthy schedule never warns. With
    60 min (the issue's example) a skip could leave exactly 3 h, and a minute of jitter would
    raise false warnings.
  - **Fallback: cron `47 */6 * * *`, window 180 min.** It dispatches only when no run started
    in the last 3 h, i.e. once the Worker has missed at least one tick; with a working Worker it
    never does. When it does dispatch, **the job fails on purpose** ("The fallback had to dispatch
    the pipeline, so the Cloudflare Worker missed its runs …"): GitHub e-mails a failed scheduled
    run, and that is the only alert that reaches Miguel without anyone reading logs. Every 6 h,
    not every 2 h: each check bills a minute, and a dead Worker is something to fix, not a mode
    to run in (GitHub's 2-hourly cron gave ~5.5 h anyway). Same code as the Worker
    (`src/fallback.js` → `tick`), Node 22, a sparse checkout of `workers/scheduler`. It also has
    `workflow_dispatch`, to check it by hand (it then only dispatches after 3 h without a run).
  - `tests/test_scheduler.py` keeps `Worker window + 120 min < RUN_GAP_WARNING ≤ fallback window`
    and the fallback's `WORKFLOW`/`REF` equal to the Worker's vars.
- **Visibility:** the Worker logs one line per tick: dispatched; skipped, with the run that served
  the tick; or why it failed. The run log warns when the previous collection started more than
  3 h before this run (`pipeline.late_run_warning`, `RUN_GAP_WARNING`; `fetch_runs`, scope
  `full`, any status; a live check is not a run), before the collection, and the run's summary
  repeats it: "Warning: the previous run (#57) started 5 h 07 min ago, more than 3 h: the
  2-hourly schedule missed a run. Check the scheduler Worker (docs/runbooks/agendamento.md)." The
  same 3 h as the review page's "A fila tem mais de 3 h" (D29).
- **Deploy:** by hand from the PC, in `workers/scheduler`: `npx --yes wrangler@4.149.0 login`,
  `deploy`, then `secret put GITHUB_ACTIONS_TOKEN` (runbook `docs/runbooks/agendamento.md`). The
  version is the one pinned for the site (`site.wrangler_version`). Review of M1 (2026-10-16): that
  config value is the only source; the version was written in five places (the Worker's
  `package.json`, its `wrangler.toml` comments, CLAUDE.md, the README and the runbook), so
  `tests/test_scheduler.py` now checks every `wrangler@<version>` in the tracked files, and
  `SiteConfig`'s default, against it; `wrangler.toml` and CLAUDE.md say `npm run deploy`, and the
  README and the runbook keep the full commands Miguel copies. No CI job: the pipeline's `CLOUDFLARE_API_TOKEN` is "Cloudflare Pages: Edit"
  only (D15), and a Worker deploy needs "Workers Scripts: Edit". Widening the token that every
  run carries, for a Worker that almost never changes, is the wrong trade. `wrangler deploy
  --dry-run` bundles it: 6 KiB, no `node:` import (checked 2026-10-15, nothing deployed).
- **Tests:** `node --test` in `workers/scheduler`, 26 tests: the request (URL, body, headers),
  the reads before it, the skip rules, a disabled workflow, failed reads, a refused or unanswered
  dispatch, the token never in a log line or error, the Worker entry (the scheduled time as
  `now`, a failure rejects), the fallback's exit codes. `uv run pytest` runs them too
  (`test_scheduler.py`, skipped without Node), next to the config checks above and the warning's
  tests (`test_scheduler.py`, `test_actions.py` through `run`).
- **Actions minutes** (private repo, GitHub Free: 2000 Linux min/month; **each job is rounded up
  to the whole minute**). Measured with `gh run list` and the jobs API over 10-13..15:
  - **Pipeline:** 19 runs, 1.7–6.2 min of wall time (median 2.3), billed 2–7 min, **3.2 on
    average**, each asking 1,080 route-months. 12 such runs a day would be 12 × 3.2 × 30 ≈ 1150.
    With D42 (review of M1, 2026-10-16) a day has **one pass** of 2,160 requests (+2 min at the
    550/min cap: ~4.3 min of wall time, **~5 billed**) and **11 regular runs** of 717 (−0.7 min,
    about a third shorter: **~2.2 billed**, most under 2 min of wall time): 5 + 11 × 2.2 ≈ 29 a
    day ≈ **880**, plus about one review-triggered run a day (a full path, ≈ 100): **~1,000**.
  - **Fallback:** ≤ 4 checks a day × 1 min ≈ **≤ 120**. GitHub ran about 5 of the 12 daily
    2-hourly crons, so probably ~60.
  - **Crawl** (`crawl.yml`, daily during the cutover week, deleted in #23 phase 2): 3 min a day,
    ~90 while it lasts.
  - **Web CI** (pull requests touching `web/`, Lighthouse included): **7–10 min a run**. There were
    11 runs in the last two days (76 min), which is ~1100 a month at this development pace and
    ~270 at one a day.
  - **Total ≈ 1,200 + Web CI: within 2000 only while Web CI stays under ~800 a month** (about
    three web PRs a day). The 5.5-hourly cron used ~400 a month for the pipeline; a real 2 h with
    the daily pass is about 2.5 times that. Past the allowance, GitHub Free without a payment
    method (or with the default $0 budget) **stops Actions in private repositories until the
    month ends, and the pipeline with it**. Knobs, cheapest first:
    1. keep the regular runs under 2 min of wall time (each one over bills 3 instead of 2; D42's
       717 requests bring most of them there);
    2. drop the ticks at 02:17 and 04:17 UTC (`17 0,6-22/2 * * *`; nights are quiet, research §4),
       −130;
    3. Lighthouse in Web CI only when pages change;
    4. a spending budget or GitHub Pro (3000).

    None is applied here. Watch *Settings → Billing and licensing → Usage*.
- **Miguel's steps** (`docs/runbooks/agendamento.md`): create the fine-grained token
  (`escapadinha` only, Actions: Read and write), deploy the Worker, store the token as its
  secret, then check two consecutive dispatched runs about 2 h apart
  (`gh run list --workflow pipeline.yml --event workflow_dispatch`). #43 closes after that.

## D42: Far months and never-seen routes once a day (2026-10-16, #44)
- **The change:** a collection run is either **the day's pass** or a **regular run**. The day's
  pass is the first run at or after `collector.daily_pass_hour` (6, Lisbon) of each Lisbon day,
  or any run when no pass was ever recorded. It asks every active route for
  `collector.daily_months_ahead` (6) departure months. A regular run asks only the routes that
  have returned a price (`last_observed_at` set), for `months_ahead` (3) months. Recommendations
  4 and 7 of `docs/research/2026-10-15-data-reliability.md`.
- **Why the far months:** a typical low is per departure month and looks back 90 days. Without
  months 4–6, Christmas/New Year, Carnaval (2027-02-09) and Easter (2027-03-28) start with about
  7 days of history when they enter the 3-month window; with them, 30–45 days. Far months are
  thin (LIS-BCN: 10 / 2 / 2 offers for Jan / Feb / Mar against 24 for November), and the cache
  keeps a found day for about 7 days, so one pass a day misses only the offers replaced within
  the same day.
- **Why never-seen routes once a day:** 121 of the 360 active routes had never returned a price in
  57 runs, 34 % of every run's requests, and dormancy waits 30 days (D23). Such a route is now
  probed once a day until its first price, then asked on every run like any other.
- **Requests per day** (12 runs, 360 active routes, 121 never seen): before, 360 × 3 × 12 =
  **12,960**. After, the pass 360 × 6 = 2,160 plus 11 regular runs × 239 × 3 = 7,887: **10,047**
  (−2,913, −22 %), plus one request per run for each open promotion in a far month. The schedule
  is the Worker's 2 h (D41; GitHub's cron, which gave ~5 runs a day, only backs it up now).
  Break-even is 4 runs a day (4,320 → 4,311), the fallback's cadence if the Worker is down;
  below that the pass costs more than it saves. Once those 121 routes are dormant (30 days
  after the 2026-10-13 discovery) the saving is gone and the far months cost their own 717
  requests a day: 239 × 3 × 12 = 8,604 → 9,321 (+8 %), still under today's 12,960. The pass
  makes twice today's requests per run (2,160, about 4 min under the 550/min cap); a regular run
  a third fewer (717 instead of 1,080). In Actions minutes (D41): one pass of ~5 billed and 11
  regular runs of ~2.2, ~1,000 a month with the review-triggered runs.
- **One place decides:** `collector/plan.py` (pure): `daily_pass_due(last, now, hour)` (Lisbon
  days through `i18n_pt.LISBON`, the clock passed in) and `plan(routes, today=, daily=, …)` →
  `Plan` (tasks in request order, `waiting` never-seen routes, `n_far_deal_months`), and where
  the far months start, `first_far_month` (month `months_ahead` + 1, also what
  `pipeline.latest_offers` reads from the pass; one function since the review of M1).
  `runner.collect` runs a `Plan`; `pipeline.run_collect(ctx, conn, now=)` builds it and records
  the pass in meta `collector.daily_pass` = `{"day", "run"}` (CI keeps no files, D25), unless
  every request failed, so the next run is the pass again. It works at any cadence (the Worker's
  2 h, D41, or the fallback's 6 h while the Worker is down): "the first run after 06:00" happens
  every day.
- **Open promotions in a far month** are asked on every run (only their route-month), so the
  recheck still judges every open promotion on every run against prices asked for its month
  (D13). Without it a regular run would expire a far-month promotion for "a viagem já não
  aparece" (the run has other prices for the route, not that month), and a due post needs a check
  under `posting.max_check_age_hours` (D32).
- **The site shows the newest prices of each route-month:** the latest run's, and for the months
  after the regular window, the latest pass's or newer (`pipeline.latest_offers` →
  `db.newest_observations`), for the calendar, the cheapest offer and the low prices in the export. The
  rules (freshness, typical lows, tiers) are unchanged. Reading only the latest run would show
  far months for one run a day and drop them at the next: two changes of the site data a day,
  each a full path (D25) for nothing. Detection stays on the run's own offers (D18): far-month
  candidates come from the pass, and the low-price link budget stays per run.
- **Dormancy unchanged (D23):** 30 days without a price. A run only judges routes it asked for
  (`routes.mark_dormant(spare=)`): a never-seen route that a discovery reactivates is probed by
  the next daily pass, not put back to sleep by a run that skipped it.
- **Run log:** `collect` and the Actions summary say which pass ran and its request count, e.g.
  `daily pass: months 1–6 of 360 routes · 2160 requests` and `regular pass: months 1–3 of 239
  routes + 1 far month of open promotions; 121 never-seen routes wait for the daily pass · 718
  requests`.
- **A missed pass warns (review of M1, 2026-10-16):** after the collection, the run log and the
  Actions summary warn when the last recorded pass (meta `collector.daily_pass`, its run's
  `started_at`) started more than 30 h before (`pipeline.missed_daily_pass_warning`,
  `DAILY_PASS_WARNING`): "Warning: the last daily pass (#57, 2026-10-15) started 30 h 05 min ago,
  more than 30 h: months 4–6 and the never-seen routes were not asked since. A pass where every
  request failed is not recorded: check the runs after 06:00 Lisbon (D42)." Passes are about
  24 h apart (26 h when the 06:00 run is late, 25 h across the autumn clock change), so 30 h
  means a Lisbon day went by without one; checked after the collection, a run that is the pass
  never warns. No recorded pass, no warning (the next run is the pass). Like D41's late-run
  warning, it only shows in the log and the summary.
- **Rejected:** months 4–6 on every run (+1,080 requests on each of 12 runs; Actions minutes near
  the 2,000 free ones); a separate cron for the pass (GitHub's cron drifts by hours; the first
  run after a Lisbon hour needs nothing new); rechecking far-month promotions only on the pass (a
  due post would wait up to a day); a `fetch_runs` column for the pass (meta is the bookkeeping
  place, and only the latest pass matters).

## D43: Baggage and agency from the Aviasales GraphQL API (2026-10-16, #46)
- **What:** after detection, every run asks the Aviasales GraphQL Flights Data API
  (`POST https://api.travelpayouts.com/graphql/v1/query`, header `X-Access-Token`, the same
  token, the same 7-day cache of searches as the REST prices, the Data API's terms, 60 requests
  a minute: `X-Rate-Limit: 60`) about its promotion candidates and low prices, one
  `prices_round_trip` query per (route, departure, return), and stores on the matched
  observation (`price_observations`, schema v14: `SCHEMA_VERSION` 14, `schema.sql`, migration
  14 = four nullable ALTERs, upgrade tested from the real v5/v7 schemas and from a v13 database
  with an offer) `with_baggage`, `baggage_code` (`0PC` = no checked bag, `1PC20` = one 20 kg
  bag), `gate` (the selling agency) and `found_at` (the exact UTC time a traveller found the
  price; the REST link only gives the day). Captions, the WhatsApp text, the slides (price block
  and the details row), promotion pages and low-price rows print the baggage line, "só bagagem
  de mão" / "com mala de porão incluída" (`i18n_pt.BAGGAGE`, `format.baggageText`), **only when
  it is known**; the review snapshot and both queue pages show it and the agency (`gate` never
  reaches a post or the site: the reviewer's context, not a traveller's). Research:
  `docs/research/2026-10-15-more-data-and-site-ideas.md` §A1 and ticket T1.
- **Never guessed (the rule):** the four fields come only from `collector/graphql.py`'s pure
  `match`; no row → all null → nothing printed (no "sem bagagem" by default); rows that disagree
  on a field → that field null. Prices are never touched (`db.set_enrichment` updates the four
  columns and nothing else; `test_enrich` compares every price before and after). The GraphQL
  API is **not a price source**: nothing it returns is stored as an observation (no new price
  string anywhere, `tests/test_traceability.py` and `web/test/traceability.test.ts` unchanged).
- **How an offer is matched (from the probe of 2026-10-15, LIS-PAR Nov 2026, 400 rows):** the
  ticket's draft said "same airline, dates and price (± 0.01 €)". The probe showed that would
  match nothing: the REST API **rounds prices to the euro** (GraphQL `value` 92.5 → REST `price`
  93, the link's `expected_price=93`), and the REST `airline` can differ from the GraphQL
  `main_airline` (MW vs FR for the same ticket). What both carry identically is the `t=` token of
  the link (`/search/LIS1011PAR12111?t=FR1794324300…_3c1739…_8657`; GraphQL `ticket_link` is the
  same path without `/search`): the ticket, the search and the agency price. So the match is **by
  that token** when the observation has a link (the exact cached offer), and only without one
  by airline, local trip dates (from the link, like the collector) and a value that matches to
  the cent or rounds (half up) to a whole-euro price. The query asks a window of a day around
  the stored local dates (`depart_date_min/max`, `return_date_min/max`: the API's timestamps can
  sit on the UTC day; GraphQL's `return_at` is not the REST one), `direct: true` only for routes
  with `direct_only`, `grouping: NONE`, `sorting: VALUE_ASC`, one page of `paging.limit` 400 (the
  API's maximum: "limit must be equal or less than 400"), `currency: eur`, `market: pt`. No
  `trip_duration` filter: the dates already pin the trip and the API counts durations its own way.
- **Budget (D23's Actions minutes):** not the bulk collector (360 routes × 1 query at 60/min is
  6 min a run, 12 runs a day: over the free minutes). `pipeline.enrich_targets` orders the run's
  open deals' observations first, then each route's low prices by discount, drops offers already
  matched (`found_at` set), and `enrich_offers` makes at most `collector.enrich_per_run` (60)
  queries, one per trip, under `collector.graphql_requests_per_minute` (55) with the same
  thread-safe `RateLimiter` and `collector.workers`: at most about a minute a run. Unmatched
  offers are asked again next run while they stay among the run's candidates and biggest
  discounts; low prices beyond the budget stay unknown (no line) until a run reaches them.
- **Archive and run rows (D18):** the answers (variables without the token + verbatim payload)
  go to `archive/runs/<id>.json.gz` under their own `fetch_runs` row (source
  `travelpayouts-graphql`, scope `enrich`, `n_requests` queries, `n_observations` rows returned,
  `n_new` offers matched), so `latest_completed_run_id` (scope `full`) and "the run's prices"
  are untouched. A failed query (a 429 after the retries, a GraphQL error, a transport error)
  is listed in the run's error and the collection run goes on: enrichment never fails `run`
  (`EnrichSummary.errors`, the step summary line "Enrichment: N GraphQL requests, M of K offers
  matched"). A 429 or 5xx waits `X-Rate-Limit-Reset`, else `Retry-After`, else a minute, up to
  `max_attempts` (3). Without the token the step is skipped with the reason.
- **Contracts, additive within v1:** `contract/site/v1` offers gain `baggage` (boolean or null,
  optional; `defs.schema.json#/$defs/baggage`) and `low-prices/<ORIGIN>.json` a 13th column
  `baggage` (`cols` const, `minItems` 13; rows are read by position, so a trailing column is
  additive); the committed fixtures were edited by hand with `null` everywhere (no run of the
  enrichment on the fixture database). The review snapshot gains optional `gate`, `with_baggage`
  and `baggage` (the pt-PT line). `site_data.PER_RUN` is unchanged: a baggage value that
  appears is a change the site should show (full path), not bookkeeping.
- **Where:** `collector/graphql.py` (`GraphQLClient`, `parse_response`, `Offer`, `match` →
  `Match`), `pipeline.graphql_client` / `enrich_targets` / `run_enrich` / `enrich_offers`,
  `escapadinha enrich [--run-id]`, `run` after `detect` and before `publish_due`, `Observation`'s
  four fields, `db.set_enrichment`, `presentation.DealView.baggage_line` / `gate` and
  `LowPriceView.baggage_line`, `captions._detail_lines` ("🧳 …"), `_ui.price_block` (`.pb-bag`)
  and slide 2's "Bagagem" row, `site_data._offer` / `_low_row`, `web/src/lib/format.ts`
  `baggageText`, `promotion.ts` / `low-prices.ts` views, `promos/[slug].astro` "Bagagem" row,
  `review_snapshot`, `web.py` + `review.html.j2`, the Function's `page.ts` ("Bagagem", "Agência").
  Tests: `tests/test_graphql.py` (the probe's real row shape, the limiter under 8 workers, 429),
  `tests/test_enrich.py`, captions, site data, `web/test` (format, explorer rows, queue page).
- **Not done here:** Miguel's check on a real promotion that the line matches what Aviasales
  shows (the issue's "Ações do Miguel"); `direct=true` on the REST collector (#41) would make the
  REST row the nonstop fare the page shows, which helps the match on routes with stops.

## D44: Confidence, new low and lead time on top of the maturity gate; a committed backtest (2026-10-18, #47)
- **Why (D3 and D24 revised):** the more-data research (`docs/research/2026-10-15-more-data-and-site-ideas.md`
  §1 and §3) showed that once a month is mature the −30 % and 15 € rule still flags "good days":
  the daily lows of a mature route-month spread with a CV of about 0,20 and the cheapest day of a
  month sits about 22 % below its median, so a −30 % day is roughly a one-in-ten day. D40 removed
  the small-sample bias; it did not change that. The research asked for three pure rules on top
  and for a committed replay so thresholds stay measured. Report:
  `docs/research/2026-10-18-detector-backtest.md`.
- **The backtest** (`src/escapadinha/backtest.py`, `scripts/backtest_detector.py`): replays the
  detector run by run on a copy of the database (opened `mode=ro`, copied into memory and migrated
  there: the file is never written) with one `DetectorConfig` per rule set, judging each
  candidate by the pipeline's own `recheck` at the runs of the next 24 h and in hindsight against
  the route-month's typical low from everything stored (its own found day left out). Reports
  candidates per day, low prices, expiries, new lows, confidence, per route kind; `--state` the
  typical low of every route-month with and without the lead-time filter. Same presence
  approximation as D40's replay (`run_id ≤ r ≤ last_run_id`). The `data-reliability` preset
  reproduces the research's table exactly (8 / 0 / 5 / 3 / 3 candidates over runs 19–57).
- **Rules** (config `detector`, `DetectorConfig`, all pure in `detector.py`, `now` and the
  route's rules passed in as before):
  - **Confidence** (`confidence(base, cfg)` → `low | medium | high`, `CONFIDENCE_LEVELS`):
    `low` below `is_mature` (D40's 7 counted days), `high` with at least
    `confidence.high_days` (14) daily lows whose coefficient of variation (`Baseline.cv`, sample
    standard deviation over the mean) is at most `confidence.high_max_cv` (0,25), `medium` in
    between. Low prices need `low_confidence` (`medium`, the D40 behaviour; `high` is the
    stricter option). The site's typical lows keep `is_mature`.
  - **New low** (`require_new_low`, default true; `new_low_margin` 0,05): a promotion candidate
    must also be at most `(1 − margin) × Baseline.min_low.price`, the cheapest eligible offer of
    the baseline window, **every day counted or not** ("cheaper than anything we have seen for
    the route-month in 90 days"). `Decision.new_low` carries the answer whether or not the rule is
    on (None without a window), so a price-cap deal has the flag too. Backtest: on the only gate
    with candidates (pre-D40), 27 → 16 candidates and 56 % → 75 % of them still a promotion today;
    every domestic candidate but one dropped (0 of 6 held).
  - **Lead time** (`baseline_min_lead_days`, 7): the baseline takes only offers with
    `detector.lead_days` (found day → departure) of at least that many days; a last-minute
    candidate is still judged against the month's typical low. Backtest: changes 12 October
    route-months (nine down, three up, median −4 %), −10 % low prices, no hindsight gain yet;
    shipped as the ticket proposed, flagged in the report as the threshold with the weakest
    evidence (0 is a one-line change).
  - `Baseline` also gains `median_lead_days`. `recheck.promotion_expiry` (the queue's
    re-evaluation, D40) inherits the new-low rule through `evaluate`: a deal undercut since
    detection expires with "já não é um novo mínimo: entretanto vimos 49 € para este mês, e 51 €
    teria de ficar 5% abaixo disso".
- **Stored and shown:** a deal stores `confidence` and `new_low` at detection (schema v15:
  `SCHEMA_VERSION` 15, `schema.sql`, migration 15 = two nullable ALTERs; upgrades tested from the
  real v5/v7 schemas; older deals keep NULLs). The review snapshot gains optional `confidence`
  (enum or null) and `new_low` (boolean or null), additive within contract v1 under D40's
  condition (the Function never validates the snapshot; a snapshot without them renders as
  before: `web/test/review/page.test.ts`). Both review pages append "· confiança média · novo
  mínimo" to the discount line (`review.CONFIDENCE_PT`, ported to `rules.ts` and checked on both
  sides through `contract/review/v1/fixtures/review-rules.json` `confidence_pt`); `deal check`
  prints them; `detect` and `stats` print the confidence (and the CV).
- **What posts claim:** captions, the WhatsApp text (which now carries the same claim line as the
  caption) and the slides' price block say "−x %" only through `DealView.claimed_discount`:
  medium or high confidence. Otherwise a new low says "o preço mais baixo que vimos nesta rota
  para partidas em novembro" (`DealView.new_low_line`; the slide tag "novo mínimo"), and a deal
  that is neither makes no claim. A deal detected before D44 (confidence NULL) makes no
  percentage claim either: honest by default. The reviewer still sees the raw `discount_pct`.
- **Values are Miguel's to choose** (the issue's "Ações do Miguel"): the report's §5 lists the
  proposal, the alternatives and what each costs today. Rejected here: estimating a seasonal
  fallback for thin months (more-data §3.5; measured gain unknown, and nothing in the backtest
  needed it), confidence on the site's route pages (the research's point 1 second half; the
  export is unchanged, a follow-up once months reach `high`), and judging candidates against the
  run archives instead of the presence approximation (cost without a question it would answer
  yet).
- **Tests:** detector (CV, floor and lead stats; the levels and `at_least`; `low_confidence`;
  a −30 % day that is not a new low is no candidate, a new low below −30 % is; the margin; the
  flag without a window and on a price cap; the lead filter and a last-minute candidate; the
  config's nesting), recheck (the new-low expiry reason), captions and WhatsApp (the claim only
  at medium or high, the new-low line alone at low, nothing otherwise), `run_detect` stores both,
  the snapshot and both pages show them (schema validated), the shared rules fixture on both
  sides, and `tests/test_backtest.py` (a synthetic database: the copy is read-only, run
  selection, one flag per candidate, the 24 h recheck, hindsight, the new-low rule, presets, the
  Markdown and JSON, `--state`, the script end to end).

## D45: Route demand from Eurostat `avia_par_pt`: page order, the far-month pass, thin-route notes (2026-10-19, #48)
- **Why:** 121 of the 360 active routes had never returned a price (D42) and nothing told a
  route that matters (Lisbon–London, 200 000 passengers a month) from one that barely flies
  (Terceira–Flores, 1 300). The research (`docs/research/2026-10-15-more-data-and-site-ideas.md`
  A12, T3) probed Eurostat's `avia_par_pt` (passengers carried per month on each airport pair
  with a Portuguese airport, compiled by INE from ANA and ANAC data; public dissemination API,
  JSON-stat, no key; reuse authorised with the source acknowledged) and proposed it as the
  demand signal: not a price source, never one (D13's no-scraping rule untouched; ANAC and ANA
  allow no reuse, A13).
- **What the pipeline does:** `demand.py` (pure) parses the JSON-stat answer by flattened
  position into `{(reporting ICAO, partner ICAO, month): passengers}`, skipping cells without a
  value; maps ICAO to IATA with `ICAO_IATA` (Eurostat labels pairs by ICAO, the provider's
  catalogues carry IATA only, and `airports.json` has no ICAO field, so a hand table of the
  Portuguese airports and the ~190 partner airports the dataset lists, each checked against the
  catalogue's name and city on 2026-10-19; a partner not in it adds nothing); sums the partner
  airports of a city through `airports.json` `city_code` (Orly + Charles de Gaulle + Beauvais =
  PAR); and gives each route the dataset's **last twelve months with any value** and their mean,
  a month without a value counting 0 (`Demand`: `pax_month`, `period`, `months`,
  `zero_months`). The reporting airport is the route's origin, so LIS-FNC and FNC-LIS each read
  their own pair. `collector/eurostat.py` makes the one GET per monthly discovery
  (`unit=PAS&tra_meas=PAS_CRD&freq=M&sinceTimePeriod=<demand.since_months ago>`), refuses an
  answer that is not the dataset, and archives it as it came under `archive/eurostat/`.
  `pipeline.run_demand` runs inside `run_discover` after the routes are applied (so new routes get
  a figure too), stores every route's figure with `db.set_route_demand` (NULLs and no months for
  a pair the dataset lacks, so a dropped pair loses its old figure) and reports a `DemandUpdate`
  (`Discovery.demand`); a failure of any kind is one more entry in the discovery's `errors`, the
  previous figures stay and the discovery and the collection go on. Dry runs fetch and report,
  store nothing.
- **Schema v16:** `routes.demand_pax_month` (NUMERIC), `routes.demand_period` (TEXT, "YYYY-MM")
  and the table `route_demand (origin, destination, month, pax)` with a foreign key to `routes`;
  `schema.sql` and migration 16 (two ALTERs + CREATE); upgrades tested from v5, v7 and a v15
  database. `Route` carries both columns; nothing else changed shape.
- **What it drives:**
  - **The day's pass (D42 revised):** `collector.deep_routes` (80) routes, ranked by
    `demand.rank_routes` (passengers descending, ties by key), get `daily_months_ahead`; the rest
    of the pass asks `months_ahead` like a regular run, and an open promotion's far month is still
    asked (`Plan.far_months`, `Plan.deep`; `describe()` says "daily pass: months 1–6 of 80 routes,
    months 1–3 of 280 routes"). With no figure stored on any route (the dataset never fetched)
    every route gets the far months, as before; a route without a figure in a fleet that has
    them is not among the busiest, so it gets the near months (the far months exist for
    Christmas and Easter on routes people fly). Regular runs are unchanged. On the real routes
    (210 of 360 with a figure on the 2026-10-19 copy, 56 of the 121 never-priced ones) the pass
    drops from 360 × 6 = 2 160 to 80 × 6 + 280 × 3 = 1 320 requests: −840 a day.
  - **Site:** `routes.json` gains `demand` (nullable, additive within v1: `pax_month`,
    `period`, `months`) and `meta.json` `demand.thin_pax_month` (config `demand.thin_pax_month`,
    5000). Origin pages and destination hubs order by the cheapest price found now, then
    passengers, then the previous order (`routes.byPriceThenDemand`); the explorer breaks a price
    tie by the route's passengers (`explore(…, demand)`, the per-origin JSON file carries the
    map). The route page shows "Procura: cerca de 141 591 passageiros por mês … (Eurostat, dados
    até dezembro de 2024)" and two notes (`routes.demandView`): "Rota com pouca procura: os
    preços aparecem raramente" when the route has no recent price and fewer than
    `thin_pax_month` passengers, "Rota sazonal" with the months at zero (hubs show a "rota
    sazonal" tag). Nothing shows for a route without Eurostat data. The number is formatted by
    `format.integer` (pt-PT space grouping, no sign): a passenger count is never a price, so the
    traceability tests need no `data-obs` and the pt-PT lint passes. "Como funciona" gains "De
    onde vêm os dados" with Eurostat's attribution line, checked by `web/test/seo.test.ts`.
  - **CLI:** `routes discover` prints the summary (dataset month, routes with a figure, seasonal
    ones, the five busiest with `i18n_pt.integer`).
- **Choices:** 36 months of history instead of the ticket's 24, because the monthly series lagged
  22 months on 2026-10-19 (24 months gave three months of values; `demand.since_months` makes it
  one setting). A month without a value counts 0 in the mean (the dataset reports tiny values
  such as 5 passengers, so a missing month is no service, not suppression; the sample has 56
  pairs with partial series and 2 explicit zeros), which ranks a summer-only route by its annual
  demand and shows its empty months. The window is the dataset's last twelve months for every
  route (one `period`), not each route's own last twelve. Thin threshold 5000 passengers a month
  (the first quartile of the routes with a figure is about 6 900; 22 of the never-priced routes
  with a figure fall under it). Rank over active routes in the plan and the mean over all routes
  on the site, each from the same stored figure.
- **Fixtures:** the committed `routes.json` and `meta.json` were hand-edited (CLAUDE.md's
  additive-field rule) to the value a regeneration writes: `demand: null` on every route (the
  fixture database has no Eurostat data) and `meta.demand.thin_pax_month: 5000`; the full
  regeneration still waits for #52. `web/test/synthetic-data.ts` gives three routes in four a
  figure (thin and seasonal ones among them), so the scale build exercises the notes and the
  order.
- **Rejected:** the ticket's "6 or 3 months read per route by the collector" (the plan stays the
  one place that decides what a run asks, D42: the rank is computed there from the routes passed
  in); INE's API (fresher, CC BY 4.0, but airport totals by country, no pairs; A12); showing the
  figure on origin pages and hubs (the number would crowd the price; the order carries it);
  keeping a dormant-but-busy route active longer (A12's idea; dormancy judges prices, D23, and
  nothing yet shows a busy route going dormant for lack of them).
- **Tests:** `tests/test_demand.py` on the real answer saved in
  `tests/fixtures/eurostat_avia_par_pt.json` (97 KB; Lisbon–Madrid December 2024 = 141 591 as the
  research read it), `web/test/routes.test.ts`, `explorer.test.ts`, `seo.test.ts`,
  `scale.test.ts`, the hub order in `route-pages.test.ts`.
- **Fix after the merge (2026-10-20):** the attribution line marked `avia_par_pt` with `<em>`, the
  first italic on the site. Both text fonts ship an italic WOFF2 (`font-display: optional`), and
  that one fetch took the About page's first paint from 2.4 s to 3.5 s on Lighthouse's throttled
  mobile (performance 0.95 → 0.84, the `web` check red; merged by mistake on a wrong exit code).
  Now `<code>`, a system font: 0.95 again. Rule of thumb: no `<em>`/`<i>` in page copy unless the
  italic faces are dropped from `astro.config.ts`.

## D46: Website first: automatic approval, paused channels, 30-minute runs, the partner's second opinion (2026-10-24)
- **Miguel's decision (2026-10-24):** "Until I say so, we're not posting anything on Instagram or
  Telegram. Only website." And: good deals should appear on the site by themselves, with the
  information deals sites lead with (deferias.pt: route, baggage, airline, best months, how to
  book). Research behind it: `docs/research/2026-10-24-faster-deal-discovery.md` (measured: a fare
  reached us a median 12.5 h after a traveller found it; none of the 13 candidates so far was ever
  reviewed; the pipeline, not the data, was the slow part).
- **Publishers paused.** `posting.publishers` is `instagram: paused`, `telegram: paused`: a new
  publisher name (`PublisherName`, `pipeline.PUBLISHERS["paused"]`, `posting.Paused` with
  `pipeline.PAUSED_REASON`). Approvals still queue their posts (D32 unchanged); every due post
  waits with the reason in `queue list`, nothing is settled, so a dry run never "publishes" what
  Miguel said not to publish. To resume: switch the two names back (D36, D38) after reading
  `queue list`: the backlog would go out for every promotion still valid and rechecked within
  `max_check_age_hours` (Telegram at once, Instagram one per run at its slots). Only Miguel flips
  this.
- **Automatic approval for the website.** Config `review.auto_approve` (`AutoApproveConfig`,
  on): in the full path, right after `render_deals`, `pipeline.run_auto_approve` takes every
  `rendered` candidate that `auto_review.disqualified` accepts (rule `median`; `confidence` at
  least `min_confidence` = `high`; `new_low` when `require_new_low`; nonstop both ways when
  `direct_only`; a known `found_at` at most `max_found_age_hours` = 48 old; under `max_per_day` = 3
  applied automatic approvals on the Lisbon day) and approves it through `pipeline.approve`:
  the **live price check is the gate**, exactly as for a human (a moved price writes nothing and
  the next recheck expires the deal). The event is an ordinary D26 event, actor
  `auto_review.ACTOR` (`auto:regras`), note `auto_review.NOTE`; with R2 the run applies the
  pending events at once (`apply_review_events`) so the export that follows publishes the deal
  in the same run's deploy (new deal → full path, D25). Both review pages show it under
  "Aprovadas" with the note and "Aprovado pelas regras (D46): já está no site"; a reject there
  expires the page as before (approved → rejected is allowed). `max_per_day: 0` reports only.
  CLI `escapadinha auto-approve`. The site's rule "only deals a human approved" becomes "only
  deals a human or the rules approved": `website.is_public` is unchanged (it reads statuses).
- **30-minute runs.** Worker cron `17,47 * * * *`, `SKIP_IF_RUN_WITHIN_MINUTES` 20 (below the 30
  minutes between ticks, or every tick would skip), `pipeline.RUN_GAP_WARNING` 2 h ("the
  half-hourly schedule missed runs"), fallback unchanged (every 6 h, window 180 min);
  `tests/test_scheduler.py` keeps `window + 30 min < warning ≤ fallback window` and
  `10 ≤ window < 30`. The Worker is deployed by hand (`docs/runbooks/agendamento.md`); **deployed
  2026-10-24 13:43 UTC** (version `0803f378`, Miguel: "corre tu o worker"; the secret stayed), so
  the half-hourly schedule runs from the 14:47 UTC tick. **Minutes:** 48 runs a day at ~2.2 billed minutes is about
  3 200 min/month. *Corrected 2026-10-24, same day:* this entry first said "over GitHub Free's
  2 000, Miguel sets a spending limit on Actions before the deploy", but the repo is public and
  GitHub does not meter standard GitHub-hosted runners in public repositories (D25 already noted
  it as an option), so there is no quota and no spending limit to set; the 2 000-minute figure
  applies only if the repo ever goes private (D41's knobs). README "Minutes used" and the
  runbook say the same.
- **Rebuild throttle (D25/D35 amended).** A live promotion's "verificado a" moves on every
  recheck, so with one on the site the site data changes every run. `run_path.decide`: when the
  **site data is the only changed component** and the last full path (meta `run.full_path_at`,
  written by `record_full_path`) is less than `site.refresh_min_gap_minutes` (120) old, the run
  stays fast ("site data changed, rebuilt at most every 120 min"); a new or expired promotion, a
  route, a new Lisbon day or code still rebuild at once. The site's "verificado a" may lag up to
  2 h; the page's small print says the hours are Lisbon's and the price can change.
- **The partner's second opinion.** Every run, after enrichment, `pipeline.run_special_offers`
  asks the GraphQL `special_offers_round_trip` once per origin with an open deal
  (`graphql.SPECIAL_OFFERS_QUERY`, introspected 2026-10-24: `ParamsSpecialOfferRoundTrip`, rows
  are the `Price` type plus `discount`, "deviation from average price for current ticket" in
  percent). A deal whose trip is on the list (`graphql.special_offer_for`: same city or airport,
  local dates and a price within rounding; the largest discount of several rows) stores
  `deals.partner_discount_pct` and `partner_offer_at` (schema v17, two nullable ALTERs; upgrade
  tested from v5/v7 and a v15 database); off the list stores null (their current list, not a
  memory). **A percentage, never a price:** nothing of theirs is stored as an observation, and the
  pages print "oferta especial do Aviasales: −48% face à média deles (visto a …)", on the review
  pages only. Answers archived under a `special_offers` run; a failing origin is reported and its
  deals keep what they had. CLI `escapadinha special-offers`.
- **Exact found time on the review pages.** The snapshot gains `found_at` (UTC, from D43's
  enrichment; null when only the day is known) and `partner_offer` (`{discount_pct, seen_at}` or
  null), both optional additions within v1 (CLAUDE.md's snapshot exception: the Function reads
  the JSON as is). Both pages print "encontrado a 24/10/2026 às 13:05 (há 1 h 20)", the age in
  bold under two hours (`format.timeAgo` on the Function, `i18n_pt.time_ago` locally, the same
  rule). The approved notice says the price is verified every 30 minutes.
- **The promotion page, deals-site style.** Live pages lead with a one-line summary ("Voos
  diretos por 69 € ida e volta, com a Ryanair, só bagagem de mão.", the price on its `data-obs`;
  `promotion.summaryParts`), and the ficha gains "Rotas" (Lisboa – Madeira (FNC) – Lisboa,
  `routesLine`), "Melhores meses" (the route's three cheapest typical lows by month, names only,
  linked to the route page where every day's price is traced; `routes.bestMonths`), "Publicada"
  (`approved_at`, Lisbon) and, live only, a three-step "Como reservar" (open the partner's search,
  confirm the final price and extras, the fare was found at X and verified at Y and can change).
  The home card shows the airline and the baggage line. No new price field, no new contract
  field: `web/test/traceability.test.ts` counts one more traced price on the live page.
- **Rejected:** Telegram paging of the reviewer and a second `publish_due` after the deploy
  (the research's items 1 and 2: Miguel wants no Telegram messages at all for now, and the
  posts are paused); a per-channel kill switch instead of `paused` (one word in config is
  clearer); dropping `checked_at` from the fingerprint (a page would then render a per-run
  field, which `tests/test_web_build.py` forbids); Google Flights or airline endpoints as
  sources (D13 stands; the research lists them with their risks for Miguel to decide).
- **Tests:** `tests/test_auto_review.py` (rules, the run step, the live-check gate, the cap, the
  switch, the command, paused publishers), `tests/test_special_offers.py` (query, parsing, match,
  run step, archive, snapshot, local page, `time_ago`), `tests/test_scheduler.py` (the new
  cadence), `tests/test_actions.py` (a full path approves and publishes; the throttle),
  `tests/test_site_data.py` (the run order with the two new steps), `web/test/review/page.test.ts`
  (found time, Aviasales row), `web/test/format.test.ts` (`timeAgo`), `web/test/pages.test.ts`
  (summary, routes, best months, publication, how to book; expired pages have neither),
  `web/test/traceability.test.ts`.
- **Addendum (Miguel, 2026-10-26): `min_confidence: medium`.** Two days in, the queue held 43
  candidates on four routes (OPO-FNC, LIS-PAR, OPO-PAR, OPO-BCN), every one a direct Ryanair new
  low 40–60 % under the typical low, and every one left to a human for the same single reason:
  the typical low's confidence was `medium` (past the maturity gate but under `high_days` daily
  lows with CV ≤ `high_max_cv`, D44), while only four LIS-FNC deals had reached `high`. Miguel
  chose to let the rules approve at medium ("Sim, muda review.auto_approve.min_confidence para
  medium"): a config change only, as D46 intended ("looser rules are a config change"); the
  other rules (new low, nonstop, found within 48 h, 3 a day, the live check as the gate) stay.
  The D44 claim rule is unchanged: a post or page says "−x %" at medium or high, so every
  automatically approved promotion may still claim its discount.

## D52: The stay length that makes sense for each destination (2026-10-28)
- **Miguel's decision (2026-10-28):** promotions respect the stay that makes sense for the
  destination. If Paris is 3–4 days, a 10-night Paris trip must not appear. Until now the nights
  range came only from the route's kind (`routes.kinds`: europe and domestic 2–10, long_haul
  7–21), the same for Paris and Madeira, and nothing had been researched. His two answers that
  decide the shape: the range applies to **everything the route's rules already shape**
  (collection, typical low, low prices, promotions), not to promotions only; and promotions
  stay per route (Lisbon → Paris and Porto → Paris apart), a traveller books from one origin.
- **One mechanism, extended:** `routes.overrides` accepts a destination as key (`PAR`: every
  route to Paris), the way `exclusions` already did; a route key (`LIS-PAR`) beats its
  destination (`routes.override_for`, used by `routes.sync`, which mirrors the override into
  the route's columns as before; `routes.resolve_rules` is the pure config-only resolution the
  backtest uses). Nothing changes in the detector, the collector, the recheck or the site: they
  read `RouteRules` as before. Rejected: a second nights rule that only filters candidates
  (two mechanisms to explain, and a typical low computed on trips the destination doesn't make
  sense for, which the backtest shows inflates it).
- **The research** (`docs/research/2026-10-28-stay-length.md`): one search per destination for
  the 158 with active routes (the bucket's database at generation 305), limited to established
  guides (Lonely Planet, Rough Guides, Rick Steves, Fodor's, Frommer's) and the official tourism
  board where one answers; where no guide gives a number (regional airports such as Doncaster,
  Brive, Memmingen), the forum consensus of those houses, marked as such. Days become nights by
  one rule per destination type, written in the note: cities `[days_min − 1, days_max]` (never
  under 2, max never under 3); beach and islands `[days_min − 1, 10]`; long-haul cities
  `[max(4, days_min), days_max + 3]`; long-haul beach `[max(5, days_min), 14]`. Examples: Paris
  2–5, Milan 2–4, Madeira 3–10, Lanzarote 3–10, New York 4–8, Maldives 5–14. Every entry in
  `config.yaml` names its source; `tests/test_stay_lengths.py` checks that the config and the
  note list the same destinations, that every range is sane, and that a 10-night Paris trip is
  refused while a 3-night one passes.
- **Backtest** (`scripts/backtest_detector.py --preset stays --days 14`, the new preset:
  `backtest.RuleSet` gains `rules` (route key → `RouteRules`), so two sets can replay the same
  detector under different ranges; the report gains a "Nights (median, max)" column): over 266
  runs (14–27/10) candidates fall from 220 to 108, low prices per run from 60 to 34, mature
  route-months from 54 to 43. Of the 142 candidates lost, 97 % would still be promotions today;
  95 are trips of 5 nights or more that the destination's range now refuses, 47 are short trips
  that stop being −30 % once the dearer long trips leave the typical low (comparing like with
  like, the intended effect). The 30 new candidates (Madeira, Paris) hold today at 67 %: the
  cost, accepted, is about half of the last fortnight's candidates and low prices.
- **Open deals outside the new range expire on the next recheck**, approved ones too:
  `recheck.recheck` already checks the route's rules before the price, with the reason "fora do
  intervalo de 2–5 noites da rota" (pipeline-owned, D26: never an approve or reject event; the
  page goes `noindex` like any expired promotion, D35). Tested end to end in
  `tests/test_pipeline.py` (an approved 3-night London deal after London moves to 4+ nights).
  On the copy: LIS-PAR 9 nights and OPO-FNC 9 nights (approved) go; LIS-FNC 5 and 7, LIS-PAR
  2 and OPO-MIL 3 nights stay.
- **Site:** nothing new. Route pages already print the range from the contract
  (`routes.ts`: "estadias de 2 a 5 noites"); the fixtures are unchanged (their routes keep the
  kinds' ranges, test data). The first run with the new config takes the full path (config.yaml
  is code in `run_path.fingerprint`) and rebuilds every route page.
- **Tests:** `tests/test_routes.py` (a destination override shapes every route there, a route key
  beats it, the 7-night fixture trip is no longer collected), `tests/test_pipeline.py` (the
  expiry), `tests/test_backtest.py` (the `stays` preset, its rules and report, the script),
  `tests/test_stay_lengths.py` (config ⇔ note). The test context clears `routes.overrides`
  like it clears `long_haul`: tests set their own.

## D51: The automatic approval has no daily cap (2026-10-28)
- **Miguel's decision (2026-10-28):** remove the limit of 3 automatic approvals a Lisbon day
  (`review.auto_approve.max_per_day`, D46). The other rules are unchanged: rule `median`,
  confidence at least `min_confidence` (`medium`, the D46 addendum), a new low when
  `require_new_low`, nonstop both ways when `direct_only`, a known found time at most
  `max_found_age_hours` old, and the live price check through `pipeline.approve` as the gate.
  `posting.max_per_day` (D32, the Instagram slot rule) is a different thing and stays.
- **What went:** the config field, `auto_review.disqualified`'s `approved_today` argument and
  its "limite diário atingido" reason, and `pipeline.auto_approvals_today` (the count of applied
  `auto:regras` approvals on the Lisbon day). With it goes the report-only mode `max_per_day: 0`
  gave: `enabled: false` is the switch; a candidate the rules refuse is still listed with its
  reason by `escapadinha auto-approve` and in the run log, as before.
- **Context:** this is the first of three changes to the promotions (the others: a researched
  stay length per destination, and one promotion per trip listing all its cheap dates instead
  of a new deal on every drop), each its own decision.
- **Tests:** `tests/test_auto_review.py`: four qualifying candidates (one more than the old cap)
  are all approved in one pass; the config has no `max_per_day`; the switch still turns it off.

## D50: The probe in a container: Chrome for Linux on a virtual display, off Miguel's desktop (2026-10-26)
- **Miguel's decision (2026-10-26):** the visible Chrome every half hour got in the way of his
  work on the PC ("para não me estorvar enquanto tou a fazer outras coisas neste PC"); asked
  for Docker and, given the trade-off below, chose it: "Avança com o Docker: Chrome Linux num
  ecrã virtual (Xvfb), perfil num volume, a tarefa agendada a chamar o docker, runbook e D50."
- **What runs where.** The price collection never ran on the PC (GitHub, D41); only the probe
  (D48, D49) does. It now runs in a container on the same PC (`docker/probe/Dockerfile`,
  `docker/probe/compose.yaml`): Python 3.14, the project from the lock (`uv sync --frozen`),
  **Google Chrome for Linux** through Playwright's `chrome` channel (the same `channel="chrome"`
  as on Windows) on a **virtual display** (`xvfb-run`): a headed browser that nobody watches,
  not headless (D48: headless is detected more and buys nothing honest). Same residential IP
  (Docker Desktop's NAT), same `escapadinha probe setup|run|status`, same pauses and walls. The
  profile lives in the named volume `pontonomada-probe`, mounted at `/root/.pontonomada`, which
  is where `cli._probe_profile` already defaults (`~/.pontonomada/probe-chrome`): no code
  change. The R2 keys reach the container from `.env` at run time (compose `env_file`); the image
  holds no secret, no database and no `data/` (`.dockerignore`). `TZ=Europe/Lisbon`,
  `shm_size: 1g` (Chrome's shared memory), `init: true` (reaps Xvfb's children).
- **The code is baked in, not mounted.** `docker compose build` copies the checkout into the
  image; a code or config change reaches the probe only after a rebuild. That is on purpose:
  until now the Windows task ran `uv run escapadinha probe run` straight from the working tree,
  so a half-edited branch was live at the next :05/:35 (2026-10-26, while D49 was being written).
  The runbook says to rebuild after `git pull`.
- **The trade-off, stated.** D48 chose a visible Windows Chrome because that is what Google
  expects from a person; a Linux Chrome with a fresh profile looks more like a server, so Google
  may answer with more consent pages or "unusual traffic" walls. The rules are unchanged: the
  first wall pauses that engine a day, nothing retries, nothing hides. **Measured on the first
  container run (2026-10-26 13:55 UTC):** `probe setup` declined both consent pages by itself
  ("Reject all", "Recusar tudo"); `probe run --limit 2` searched 2 of 2 trips, Google Flights
  priced 1 and Kayak 2, no wall, 4 minutes, the file in R2 for the next pipeline run. Kayak gave
  no sign of caring either way.
- **Not done here:** a VNC/noVNC view into the container (the container's profile is its own,
  separate from the Windows one, so a consent page without a reject button cannot be answered
  by hand yet: the runbook says to report it); a Linux cron inside the container (the Windows
  task keeps the schedule and the log, now calling `docker compose run`); a second machine.
- **Rejected:** headless Chromium (D48); mounting the working tree into the container (brings
  back the half-edited-branch hazard and clashes with the Windows `.venv`); an off-screen
  window on Windows (`--window-position`: Chrome treats an occluded window as hidden and
  throttles it; it still steals focus on launch); running the task "whether the user is logged
  on or not" (Docker Desktop lives in the user's session).
- **Tests:** `tests/test_probe_docker.py` (the image's Python is the project's, the `chrome`
  channel and Xvfb, headed, the same `escapadinha probe` command, the lock; compose: the profile
  volume at the CLI's default home, `env_file` and no secrets in the image, `.dockerignore`).

## D47: The airlines' own fares next to the cache: Ryanair's fare finder, the link goes to the seller, a comparison per source (2026-10-24)
- **Miguel's decisions (2026-10-24), after the research in
  `docs/research/2026-10-24-faster-deal-discovery.md` and D46:** no paid data source ("Eu não
  quero pagar por APIs"); accept D13's risk ("Aceitar os riscos do D13"); go through the
  airlines' own endpoints ("Segue pelos endpoints das companhias"); several sources per
  promotion, for comparison ("Não quero só 1 solução se pudermos implementar várias para fins
  de comparação"); the deals sites' own mix is good enough ("O deferias.pt utiliza tanto as
  companhias como o Skyscanner + Kayak"). Phase 1 (this entry) runs on GitHub; phase 2 (a browser
  probe on Miguel's own PC for Google Flights / Kayak, where a residential IP and a real browser
  profile are what those sites expect) is designed in `docs/plan/2026-10-24-pc-probe.md` and
  installed by him.
- **What the rule is now (D13 amended, not dropped).** Reading public fares with an automated
  client is a breach of a site's terms, not a crime: in the EU it is enforceable as a contract
  (CJEU C-30/14 Ryanair v PR Aviation, 2015), and the German BGH (I ZR 224/12, 2014) held that
  scraping as such is not unfair competition but circumventing a site's technical barriers can be.
  So the line moves from "no automated access" to **"no step around a technical barrier"**: a
  plain request to the JSON the airline's own page calls, one at a time, with a user-agent that
  names the site (`ryanair.user_agent`: `pontonomada.pt price check (+<base_url>/sobre/)`),
  no retries, and the **first 403, 429 or challenge page stops the pass and pauses the source**
  (`airlines.<source>.blocked_hours`, meta `airlines.<source>.blocked`). No stealth plugins,
  proxies, captcha solving or user-agent spoofing, ever. Low volume: a bounded, rotating hot list,
  never a bulk collector. The worst case is a cease-and-desist, not a surprise.
- **Measured before building (2026-10-24):** Ryanair's `farfnd/v4/roundTripFares` answers a
  plain `curl` with that user-agent in 0.24 s from the PC and **0.42 s from a GitHub-hosted
  runner** (a throwaway workflow on `master`, removed here): one JSON per airport pair and
  outbound window, the cheapest return per outbound day within the trip length, with each leg's
  `priceUpdated`. **Wizz Air is out:** `wizzair.com/buildnumber` (the version every Wizz endpoint
  needs) redirects to an AWS WAF "Human Verification" page on the first request, from the PC and
  from the runner alike; by the rule above that door stays closed. easyJet blocked the 2026-10-15
  fetch (research A-series). Ryanair is 2 665 of the copy's 7 845 observations (34 %), 259
  (origin, destination, airport) pairs carry a Ryanair or Wizz fare.
- **Source `ryanair` (`collector/ryanair.py`).** `parse_fares` (pure): one `Observation` per
  fare, `source="ryanair"`, the route's city code as `destination` and the airport the fare lands
  at as `destination_airport`, nonstop by construction (the fare finder lists Ryanair's own
  flights), `found_at`/`found_date` = the newer `priceUpdated` of the two legs (when Ryanair last
  changed the price: the closest thing to a traveller's "found" time for a live source),
  `gate="Ryanair"`, `deep_link` = ryanair.com's flight selection for the same dates
  (`booking_url`: the airline's page, no tracking, no commission). Dropped, never patched: a fare
  without both legs or a positive summary price, or outside the route's nights range.
  `RyanairSource.fetch_fares(origin, destination, airport, month, rules=)` is not a
  `PriceSource` (those take a city code; the airline flies to airports). `RyanairError.kind`:
  `blocked` (403/429, or 200 that is not JSON), `http`, `api`. `insert_observations` now stores
  `gate` and `found_at` when the source gives them (the GraphQL enrichment, D43, still sets them
  for Aviasales offers and matches Aviasales offers only).
- **Hot list (`collector/hotlist.py`, pure; `pipeline.run_airlines`, CLI `airlines`).** Pairs =
  (active route, airport) for every airport the cache's Ryanair offers used in the last
  `lookback_days`, busiest route first (Eurostat demand rank, D45, then offers seen). Each run
  asks **the open promotions' months on Ryanair flights first** (their recheck and the comparison
  need the airline's price every run), then the next `max_requests_per_run` (pair, month) tasks
  of a rotation over pairs × the run's `months_ahead` (cursor in meta `airlines.ryanair.cursor`):
  20 per run, 48 runs a day, about 450 pair-months, so every pair-month about twice a day, under
  1 000 requests a day at 20 a minute. Its own run row (source `ryanair`, scope `airlines`):
  `latest_completed_run_id` keeps keying on the `full` collection run, and detection, the recheck
  and the export read the airline's offers through `observations_seen_since` that older run. The
  step runs right after the collection and never fails the run (`cli._airlines`). `routes.
  last_observed_at` counts an airline sighting.
- **The link goes to the seller (D13's "same place as the link", kept).** A deal from an airline
  observation gets `affiliate_url` = its `deep_link` (`ensure_affiliate_links`, no partner API
  call); the name stays, the meaning is "the booking link". The site exports `link_kind`
  (`partner` | `airline`), `seller` and `source` on the promotion (contract v1, additive) and
  `labels.disclosure.direct` ("Ligação direta ao site da companhia aérea: não recebemos comissão
  por esta reserva."), and `cta.bookingCta(…, kind, seller)` gives an airline link the airline
  note and that disclosure (it throws without the label: an airline button is never shown under
  the affiliate disclosure, which would be false). "Como reservar" says "abre o site da Ryanair".
- **The recheck trusts the deal's own source only.** `_fetch_trip_month` (behind `price_now`,
  `live_check`, the approval gate) prices a Ryanair deal at Ryanair (same airport pair and
  month); `run_recheck` judges a deal against the newest offers **of its own source** on the
  route. Another source's price of the same trip is a comparison, never a confirmation: the
  price shown must still hold where the link goes. `check_failure` names Ryanair's errors in
  pt-PT. The review Function's live check is the prices_for_dates port, so the snapshot carries
  `live_check.source` and the source's own `query` (`pipeline.live_check_query`; the schema's
  `query` is now one of the two shapes), and **the Function refuses to check or approve a deal
  from an airline source** (`handler.pipelineOnly`, 409, pt-PT): the automatic approval (D46)
  or `deal approve` on the PC decide those. Rejecting needs no price and stays allowed.
- **A comparison per source.** `pipeline.also_seen(conn, obs)`: the newest stored observation of
  the same trip (route, dates) at every other source, cheapest first
  (`db.trip_observations_by_source`). The snapshot carries `source`, `source_label` and
  `also_seen` (each with `price_eur` and `observation_id`: `tests/test_review_events` traces
  them), both review pages show "Fonte" and "Também visto" (`presentation.seller_label`:
  "Aviasales via Kiwi.com", "Ryanair"), and a live promotion exports `also_seen`
  (`{source, label, obs, eur}`, checked by `tests/test_site_data` like every price) which the
  promotion page lists as "Também visto · Aviasales via Kiwi.com · 44 €", each on its
  `data-obs`. The comparison prices change between runs: that is shown content, so it goes
  through the fingerprint and the D46 throttle, not `PER_RUN`.
- **Fixture by hand (allowed by the contract rule):** `contract/site/v1/fixtures/labels.json` regenerated
  from a fixture export on an empty database (it holds no database data; `tests/test_affiliate_blocks`
  compares it with such an export), which adds `disclosure.direct`. The other committed fixtures
  keep their pre-D47 shape: every new promotion field is optional and absent there.
- **Config `airlines.ryanair`** (`AirlinesConfig`): `enabled`, `max_requests_per_run` 20,
  `requests_per_minute` 20, `blocked_hours` 24, `lookback_days` 90. Nothing in `.env`: the fare
  finder needs no key.
- **Not done here, on purpose:** Ryanair offers are **not low-price rows** on route pages: a row
  cannot say its link kind yet and the list carries one partner disclosure for all its buttons;
  the airline's fares still count for detection, the route's cheapest and the calendar (prices,
  no button). The posts' caption and WhatsApp text keep `presentation.DISCLOSURE` ("links de
  afiliado") for every deal, airline ones included: both channels are paused (D46) and that text
  must change before an airline deal is ever posted. Wizz Air (behind a WAF challenge), easyJet
  (blocked us), TAP and Vueling (no stable fare-calendar JSON) have no source; for them the
  cache and its `price_now` stay the check. Phase 2 (the PC probe) is a separate design.
- **Rejected:** a paid scraping API (SerpApi, Apify: Miguel pays for no API); a headless browser
  from the GitHub runners (it is caught in hours and only survives with stealth plugins and
  proxies, the very barrier-circumvention that turns a terms breach into something worse, and
  it is slow and brittle); retries on 403/429 (the pause is the point); making `RyanairSource` a
  `PriceSource` behind a city code (an airline flies to airports: the pair is explicit);
  converting ryanair.com links through the partner links API (not a partner brand: a hand-built
  URL to the airline is not a `marker=` URL and D19 does not apply); filtering the recheck's
  "latest" by source only for airline deals (the rule is the same for every source).
- **Tests:** `tests/test_ryanair.py` (parsing, the found time, the link, the request window,
  the user-agent, blocked/http/api without retries), `tests/test_hotlist.py` (pairs, rotation,
  promotions first, wrap-around, empty inputs), `tests/test_airlines.py` (the step and its run
  row, a wall that pauses and the later retry, off/empty, a Ryanair fare that becomes the deal,
  its airline link, its live check and recheck at Ryanair only, the snapshot and the export with
  `link_kind`, `seller`, `also_seen`, the direct disclosure, no Ryanair low-price rows),
  `tests/test_site_data.py` and `tests/test_review_events.py` (the price tracers learn
  `also_seen`), `web/test/cta.test.ts` (the airline kind), `web/test/review/decision.test.ts`
  (the Function leaves airline deals to the pipeline).

## D48: The browser probe on Miguel's PC: Google Flights as a comparison source (2026-10-24)
- **Miguel's decision (2026-10-24):** "Avança com a fase 2: constrói a sonda para o meu PC, só
  Google Flights para começar, e dá-me o runbook de instalação." Design: `docs/plan/2026-10-24-pc-probe.md`;
  runbook (pt-PT, Task Scheduler): `docs/runbooks/sonda.md`. Phase 2 of D47.
- **Why at home and only there.** The agencies Miguel wants to compare with have no price API
  for us and sit behind bot walls; the one page that compares them live is a metasearch, and from
  GitHub's runners an automated browser is caught within hours and only survives with the
  barrier circumvention D47 forbids. On his PC, with his residential IP and a real Chrome profile,
  one search at a time at a human pace is what the site expects from a person comparing fares.
  Nothing hides the probe: a visible Chrome (`probe.headless: false`; true is detected more
  often and buys nothing honest), no stealth, no proxy, no captcha solving; the first wall
  (consent page, "unusual traffic", captcha, 403) ends the run and pauses the probe
  `probe.paused_hours` (`probe/state.json`).
- **Read once before building (2026-10-24, from this PC):** the public `q=` URL ("Flights from
  LIS to STN on … returning … nonstop one adult economy", `hl=en&gl=PT&curr=EUR`) lands on round-trip
  results after a consent page (declined once per profile); each row's text is
  `3:10 PM | – | 6:00 PM | Ryanair | 2 hr 50 min | LIS–STN | Nonstop | 137 kg CO2e | Avg emissions | €65 | round trip`
  (the operating carrier appended as "RyanairOperated by Malta Air"); choosing the outbound
  lists the returns with the round-trip total; choosing the return opens the booking page, whose
  sellers are links labelled "Continue to book with Ryanair airline for 65 euros" (an OTA reads
  "… with eDreams online travel agency for …"), with a "View options" button for more. Google's
  own price insight ("€65 is low … usually €100–315") is there too and is not read (its measure,
  not a price of ours: the D46 rule for the partner's opinion would apply).
- **The pipeline decides what is searched (`probe/wanted.json`, `pipeline.run_probe_wanted`,
  after detection on every run):** every open promotion's trip first (the comparison next to
  it), then the cheapest fresh nonstop offer of each route, busiest route first (Eurostat rank,
  D45), in rotation (meta `probe.cursor`), up to `probe.max_trips` (10: three page loads a trip,
  8–12 minutes a run at 20–45 s pauses). Pure: `probe/wanted.py`. *Same evening:* the first
  list had 23 open promotions for a limit of 10, so the rotation now runs over the promotions
  and then the routes' offers as one sequence; every promotion gets its turn within three runs.
- **The probe (`escapadinha probe setup|run|status`, `probe/runner.py`, `probe/google_flights.py`):**
  `setup` opens the probe's own profile (`~/.pontonomada/probe-chrome`, never Miguel's) on the
  home page and declines consent (the most privacy-preserving answer); `run` reads the list,
  searches each trip (`gf.search`: results → cheapest nonstop outbound → cheapest return →
  booking options, with `expand_options`; the parsers are pure over the page's texts and never
  guess: no price, no row), pauses between trips, writes one `probe/results/<stamp>.json`
  (every page text it used, per trip) and `probe/state.json`; a `Wall` stops it (exit 2) and the
  results read so far are still written. Playwright over the PC's Chrome (`channel="chrome"`) is
  the only browser code (`ChromeFlights`); tests drive a fake `Flights`.
- **The import (`pipeline.run_probe_import`, after the airline step on every run, never failing
  the run):** one run row (source `google_flights`, scope `probe`), an observation per
  (trip, seller) with `gate` = the seller, `airline` from the row's carrier name when the pt-PT
  table knows it, `found_at` = the read time, **`deep_link` None**; the files are archived with
  the run and deleted; a file that cannot be read is listed and left for the next run.
- **A comparison source (`pipeline.COMPARISON_SOURCES`, `comparable`).** Its offers never enter
  detection (candidates, low prices, the typical low: `run_detect`, `route_history`), nor a
  route page (`site_data` `by_route`): D47's rule that a deal links to, and is rechecked at, a
  source the pipeline can ask itself, and the probe is neither always on nor a seller. They
  show as "Também visto" (`also_seen`, now one entry per source **and seller**:
  `db.trip_observations_by_source` keys by `(source, gate)`), "Google Flights via eDreams 55 €",
  on both review pages and the promotion page, each on its observation. They are also a hot
  signal only in that sense; a probe price never changes a status.
- **Config `probe`** (`ProbeConfig`): `enabled`, `engine` (google_flights), `max_trips` 10,
  `pause_seconds_min/max` 20/45, `paused_hours` 24, `headless` false, `profile_dir` (default
  under the user's home). Nothing in `.env`: the PC's existing R2 keys (the ones `store pull`
  uses) carry the probe's writes; a token restricted to `probe/` is a later hardening.
- **Not done here:** Kayak and Skyscanner (the design's order: only if Google Flights leaves a
  gap); OTA sellers appear only when Google lists them for the itinerary (often the airline
  alone on Ryanair routes); the scheduled task is Miguel's to create (runbook); no second engine
  abstraction beyond `probe.engine`.
- **Rejected:** running the probe on GitHub (D47); headless by default; a probe-only
  promotion or button; letting the probe pick trips; reading Google's price insight as a price.
- **Tests:** `tests/test_probe.py` (the wanted list and its rotation, the parsers over the real
  texts, `search` over a fake browser incl. a wall, results → observations without links, the
  runner's file and state, pause and retry after a wall, the pipeline's list and import, the
  comparison-source exclusions and the per-seller "Também visto").

## D49: Kayak as the probe's second engine; a pause per engine (2026-10-26)
- **Miguel's decision (2026-10-26):** "avança com o Kayak": the second comparison source next to
  Google Flights, the way deferias.pt compares the airlines with Skyscanner and Kayak (D47). Per
  trip the probe runs Google Flights, then Kayak, in one browser, never two in parallel.
- **Read once before building (2026-10-26, from this PC, `docs/research/2026-10-26-kayak-probe.md`):**
  kayak.pt answers a plain visit from a visible Chrome without a wall: a cookie dialog with
  "Recusar tudo" (declined once per profile), then the public search URL
  (`/flights/OPO-FNC/2026-12-17/2026-12-21/1adults?sort=price_a&fs=stops=0`: one adult,
  cheapest first, nonstop filter) lands on a list of numbered cards
  (`[role=group][aria-label="Resultado número N"]`) that streams in for about ten seconds.
  A card names the airlines, the times and "direto" per leg (and, in its segment checkboxes'
  labels, "Segmento 1: Ryanair, OPO 6:30 - FNC 8:30."), the bag counts, the fare and the price
  of the cheapest booking site for that itinerary. **The sellers themselves are not on the
  page:** expanding the card shows "11 ofertas desde 44 €", and its "Selecionar" link goes
  straight to the seller (ryanair.com). Reading them would cost a page on every seller's site:
  not done.
- **Engine `kayak` (`probe/kayak.py`), one page load a trip:** `search_url`, `parse_card`
  (pure, over the card's text and labels: price with the pt-PT thousands dot, two legs, nonstop
  only when both legs read "direto", the airline of each leg from its segment label, else None),
  `cheapest_nonstop`, `wall_reason` ("press and hold" / `/security/`, captcha, "unusual
  activity", access denied), `search` → the shared `Search` with one `Option(seller=None,
  kind="metasearch", price)`. Source `kayak`, label "Kayak": the comparison reads "Também visto ·
  Kayak · 44 €" (`seller_label` prints the source alone when there is no seller). The airline
  code comes from the pt-PT table as on Google Flights; a name it does not know stays None.
- **One browser, every engine (`probe/engine.py`, `probe/browser.py`).** The shapes the engines
  share (`Result`, `Option`, `Search`, `View`, `Wall`, `airline_code`) moved to `engine.py`
  (`google_flights` re-exports them); `browser.ChromeSession` is the probe's one Chrome window
  (the profile of D48), and `google_flights.ChromeFlights` / `kayak.ChromeKayak` are adapters
  over the same page. `probe run` opens one session and binds the configured engines in order
  (`engine.Bound`); `probe setup` declines consent on each engine's home page. Config
  `probe.engines: [google_flights, kayak]` replaces `probe.engine` (a list in search order, each
  engine once, at least one; `ProbeEngine`). The run's pause between trips stays; between two
  engines on the same trip the probe takes half of it.
- **A pause per engine (`probe/state.json` `engines.<name>`).** A `Wall` ends the run **for
  that engine only**: the others go on with the trip and the rest of the list. The state keeps
  `last_searched` / `last_priced` per engine and, after a wall, `paused_until`, `reason`,
  `paused_at` under the engine's name; `runner.paused_until(state, now, engine)` also honours a
  pre-D49 top-level pause (the whole probe's). A run skips a paused engine, and with every
  configured engine paused opens no browser (`status: paused`). `probe status` lists the
  engines; `ProbeSummary.engines` and `describe()` say what each engine did ("kayak: 0 searched,
  0 priced, press_and_hold, paused until …"). Exit code 2 on any wall, as before.
- **Results and import.** A record carries `engine` (`results.record(…, engine=)`); the
  document lists `engines` in search order and keeps `engine` (the first) and `stopped` as
  engine → reason for pre-D49 readers (a plain reason is read as Google Flights'). `to_observations`
  maps the record's engine to its source (`results.SOURCES`; a record without `engine` is the
  document's engine, a record from an unknown engine yields nothing) and stores `gate` null when
  the engine names no seller. The import's run row is source `probe` (scope `probe`): its
  observations carry each engine's source. `pipeline.COMPARISON_SOURCES` is `probe.SOURCES`
  (both engines): Kayak prices never enter detection, a low price, a typical low or a route
  page either.
- **Not done here:** Skyscanner (the design's "only if the first two leave a gap", and the most
  aggressive with automation); Kayak's sellers (above); a Kayak link (there is none to a seller
  that is not Kayak's own redirect); any change to the site (the promotion page already lists
  every comparison with its label).
- **Rejected:** kayak.ie for English texts (the comparison should be what a traveller in
  Portugal sees; the parsers read pt-PT); following "Selecionar" to read the sellers (a page view
  on each seller's site per trip); a second Chrome profile or window per engine (two browsers);
  retrying a Kayak wall on Google Flights' schedule (each engine pauses on its own).
- **Same afternoon, Google Flights' misses:** the first two-engine runs had Google Flights at
  `no_nonstop` / `no_return` / `no_options` on 18 of 50 trips where Kayak priced the same
  nonstop Ryanair itinerary; a replay of one (OPO–STN) parsed every row. The cause was timing:
  `[role=list] li` also matches the passenger picker ("Adults…"), present before any result, so
  `wait_for_selector` returned at once and `rows()` read the list before the results streamed
  in (the same after choosing the outbound, and for the booking labels). `ChromeFlights` now
  waits until a row parses (a price on it), up to 30 s on the results page, 20 s on the return
  list, 15 s for a "book with" label (`_settle`; a wait for rendering, never a retry of a
  request), and `search` reports `no_results` when no row carries a price (the passenger rows
  alone are not results). Tests: the passenger rows as a page. *Later the same day:* the 13:35
  run died on Playwright's `TimeoutError` (kayak.pt took over 60 s to answer one navigation) and
  lost the nine trips already read: a browser error that is not a `Wall` now counts as that
  engine's failed search (`EngineSummary.errors`, state `last_errors`, a line on stderr) and
  the run goes on; only a wall pauses an engine, and nothing is retried.
- **Tests:** `tests/test_probe.py` (the card parsers over the real texts incl. a mixed-carrier
  and a one-stop card and a sponsored one, the URL and the walls, `search` over a fake Kayak
  incl. a wall, Kayak results → `kayak` observations labelled "Kayak" and excluded by
  `comparable`, a two-engine run where Kayak walls on the first trip and Google Flights finishes
  the list, the per-engine pause kept on the next run, every engine paused → no browser, the
  pre-D49 state and file shapes, `ProbeConfig.engines` validation).

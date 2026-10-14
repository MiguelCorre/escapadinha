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
  `low_threshold` (0.15) below a **mature** typical low (≥ `min_baseline_days`), one per trip
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
  (e.g. a hash of its files). Tests validate the export with
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
  fewer than `min_baseline_days` days, so the site says "ainda sem dados" instead of a number.
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
  promotion pages, live and expired. The Jinja site stays the live one until the cutover (#23);
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
  on the expired page). No font preload and no italic on first paint: Lighthouse's simulated
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
- **Deploy wiring:** wrangler compiles `<cwd>/functions` during `pages deploy`, and the deploy ran
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
  (`isWeekendTrip`: out Fri/Sat, back Sun/Mon within 3 nights; `fitsPonte`). Python tests the
  calendar and the windows (`tests/test_pontes.py`).
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
- **Not done here:** a nav link, JSON-LD and the sitemap, affiliate blocks (#18), the drafts
  themselves (#19).

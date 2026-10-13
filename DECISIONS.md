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
  Left in #22: the Instagram rename with its own Project (step 9).

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
  shown meanwhile without a button. Rows older than 30 days are pruned (their offers left the
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

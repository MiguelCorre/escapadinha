# Spec: Escapadinha v2 — Portugal-wide flight deals site, explorer and distribution

Status: draft for Miguel's approval · Origin: planning interview 2026-10-13 (`docs/plan/2026-10-13-interview.md`) · Vocabulary: `GLOSSARY.md` · Prior decisions: `DECISIONS.md` (D1–D15)

Brand name decided 2026-10-13: **Ponto Nómada** (DECISIONS D16). Domain and Instagram handle rename are still pending (M6); `ondestaanocas.pages.dev` and `@ondestaanocas` remain placeholders throughout.

## Problem Statement

Miguel wants a Portuguese travel-deals brand in the mould of deferias.pt: a site and social channels that surface genuinely cheap flights *from Portugal*, help people find flights, and offer itineraries and travel tips, monetised through affiliate links (and later ads).

The v1 prototype proves the mechanics (collect → price history → detect against the route's own typical low → render slides → human approval → static site) but it is far from the product:

- It only watches **10 hand-picked routes** from Lisbon and Porto. "All flights leaving Portugal" is ~300 direct routes from six airports plus long-haul destinations with a stopover, and the list must maintain itself.
- It collects from **Miguel's PC** via Task Scheduler, so the price history (the project's core asset) has holes whenever the PC is off, and it isn't backed up.
- It stores every API response row verbatim; at 300 routes that is ~170k rows/day, most of them repeats.
- Approval needs the PC and a local web page; nothing is reachable from a phone.
- The site is a hand-styled Jinja template with no identity: it looks generated. There is no explorer ("where can I go from Porto for under 60 €?"), no destination or origin pages, no itineraries, no tips, and no live search.
- Nothing is published to Instagram or any other channel automatically; every post is manual.

## Solution

Grow the prototype into a Portugal-wide product in six milestones, keeping the rules that already make it trustworthy (**no price without a stored observation**, live verification, automatic expiry, human approval of anything that carries the brand):

1. **M1 Data at scale** — routes discovered automatically from the data provider's route catalogue for LIS, OPO, FAO, FNC, PDL and TER, plus a curated list of ~20 long-haul destinations with their own rules; per-route rules (direct-only, nights range); dormant/seasonal lifecycle; deduplicated observations with raw payloads archived; two publication tiers (automatic *low prices* vs. human-approved *promotions*); a versioned JSON contract for the website. The pipeline runs on **GitHub Actions** with the SQLite database and raw archives in **Cloudflare R2** (free tiers), and the review queue becomes a **Cloudflare Pages Function** behind Cloudflare Access so Miguel can approve from his phone.
2. **M2 Design** — three visual directions built as real HTML with real data; Miguel picks; a written design system (type, colour, spacing, components, photo treatment) becomes the contract for the site. Provisional typographic logo.
3. **M3 Website** — Astro + Tailwind static site fed by the JSON contract: home, promotions, route pages, origin pages, destination hubs, the **explorer** (budget, month, direct-only, nights, weekends, Portuguese long weekends/"pontes"), itineraries and tips, discreet Aviasales search widget, cookieless analytics. Replaces the current site on the same Cloudflare Pages project.
4. **M4 Content** — reviewed MDX itineraries and tips (Claude drafts, Miguel approves), one itinerary per destination with published promotions, affiliate blocks for eSIM, insurance and activities.
5. **M5 Distribution** — Instagram Graph API carousel + story publishing from a scheduled queue after approval, Telegram channel posts, copy-paste WhatsApp text, all gated by Miguel's approval.
6. **M6 Brand** — decision point for the final name, `.pt` domain and logo, with redirects; must be settled before M3 goes live.

## User Stories

### Coverage and data (M1)
1. As Miguel, I want every direct route from LIS, OPO, FAO, FNC, PDL and TER discovered automatically from the provider's route catalogue, so that "all flights from Portugal" does not depend on a hand-written list.
2. As Miguel, I want the route catalogue re-discovered once a month, so that new seasonal routes appear by themselves.
3. As Miguel, I want a route with no observations for 30 days to become dormant (no API calls, route page kept with a notice), so that we do not waste requests on routes that no longer fly.
4. As Miguel, I want a dormant route reactivated automatically when the next discovery finds it again, so that seasonal routes come back without my intervention.
5. As Miguel, I want nothing ever deleted from the price history, so that the baseline keeps improving and every past promotion stays traceable.
6. As Miguel, I want a curated list of ~20 long-haul destinations from LIS and OPO with their own rules (≤1 stop each way, 7–21 nights), so that we can post the "Japan from 564 €" style deals without breaking the direct-only rule for Europe.
7. As Miguel, I want per-route rules (direct-only, nights range, thresholds) with sensible defaults per route kind (Europe/North Africa, long-haul, domestic/islands), so that I only override the exceptions.
8. As Miguel, I want domestic routes to and from the islands covered as the "Ilhas" category, so that residents and visitors of Madeira and the Azores are served.
9. As Miguel, I want identical offers seen in consecutive runs stored once (with first/last seen and a seen counter) instead of as new rows, so that the database stays small enough to live in object storage.
10. As Miguel, I want every run's raw API responses archived compressed and every observation to point to its run, so that any price shown can still be traced to the exact payload it came from.
11. As Miguel, I want the pipeline to run on GitHub Actions every two hours with the database stored in Cloudflare R2 between runs, so that collection no longer depends on my PC being on.
12. As Miguel, I want the routine run to do only collection, recheck and detection (fast path) and to render slides, rebuild and deploy the site only when there is something new, so that we stay inside the free Actions minutes.
13. As Miguel, I want a daily database backup kept for 30 days, so that a corrupted or lost database can be restored.
14. As Miguel, I want concurrent runs prevented (lock), so that two runs never write the same database file.
15. As Miguel, I want the Windows Task Scheduler job kept as a fallback until the Actions pipeline has run cleanly for a week, then unregistered with a documented command, so that there is no gap in collection during the migration.
16. As Miguel, I want a Pixabay photo found automatically for every discovered destination (with manual query overrides), so that slides for 150+ destinations do not need me to pick photos.

### Detection and publication tiers (M1)
17. As a visitor, I want route pages and the explorer to show recently found *low prices* automatically (below the route's typical low, with a visible "found on" date), so that I see real data without waiting for a human.
18. As Miguel, I want only prices at least 30 % and at least 15 € below the typical low to become *promotion candidates* in my review queue, so that the queue holds things worth posting.
19. As Miguel, I want the baseline to stay the typical low (median of daily lows per route and departure month), with the plain average shown only as context on route pages, so that promotions are measured against the floor, not the mean.
20. As Miguel, I want promotions re-verified every run and expired when the price rose, the trip vanished, the price is stale or the trip stopped being direct where required, so that nothing stale carries the brand.
21. As a visitor, I want an expired promotion page to say so clearly, lose its booking button and be removed from search engines, so that I am never sent to a price that no longer exists.
22. As Miguel, I want a test that fails if any price rendered on the site or in a post cannot be traced to a stored observation, so that the "never fabricate" rule is enforced, not just intended.

### Review from anywhere (M1)
23. As Miguel, I want to open the review queue on my phone, protected by Cloudflare Access with my e-mail, so that I can approve or reject without my PC.
24. As Miguel, I want each queue item to show the slides, price, dates, airline, discount, found/verified timestamps and a live price check, so that I can decide in under two minutes.
25. As Miguel, I want approve/reject/published decisions recorded as append-only events applied by the pipeline, so that my decisions and the running pipeline never overwrite each other.
26. As Miguel, I want approving a promotion to trigger a pipeline run within minutes, so that the site and channels update without waiting two hours.
27. As Miguel, I want the local CLI review commands to keep working against the same event log, so that I can still work from the terminal.

### Design (M2)
28. As Miguel, I want three visual directions presented as real HTML pages (home + promotion page with real data each), so that I choose a look by seeing it, not by reading adjectives.
29. As Miguel, I want the chosen direction written down as a design system (fonts, palette, spacing, radii, components, photo treatment, tone of voice), so that every page and every slide follows the same identity.
30. As Miguel, I want a provisional typographic logo in SVG that works on light and dark backgrounds, so that the brand is consistent until the name is final.
31. As Miguel, I want the Instagram slide templates restyled to the same design system, so that the feed and the site look like one brand.

### Website (M3)
32. As a visitor, I want a home page with featured promotions, a compact explorer and the latest itineraries, so that I see value in the first screen.
33. As a visitor, I want a promotions list filterable by origin airport, so that I only see departures near me.
34. As a visitor, I want a page per route (e.g. Porto → Paris) with the typical low per month, a calendar of the cheapest found prices, recent low prices, a link to the destination itinerary and a live search widget, so that I can decide when to go and book.
35. As a visitor, I want a page per origin ("flights from Porto") listing every destination with its current cheapest found price, so that I can browse what is reachable.
36. As a visitor, I want a page per destination with all Portuguese origins, best months, the itinerary and related tips, so that the site answers "how do I get to Rome cheaply and what do I do there?".
37. As a visitor, I want an explorer where I pick an origin, a maximum budget, a month, nights range, direct-only and weekend-only, and see destinations sorted by price, so that I can find where to go instead of where I already decided.
38. As a visitor, I want a "pontes e feriados" filter and dedicated pages per Portuguese long weekend (e.g. "Ponte de 1 de dezembro desde o Porto"), so that I can plan around national holidays.
39. As a visitor, I want every "book" link to open the partner (Aviasales, euros, pt market) with a tracked affiliate link, with an advertising disclosure visible, so that I know what the link is and the brand earns.
40. As a visitor, I want the live search widget available on route and destination pages when I need current prices, so that I can search without leaving the site's context.
41. As a visitor on a phone, I want every page to load fast and read well (Lighthouse mobile ≥ 90 on performance, SEO and accessibility), so that the site feels professional.
42. As a visitor, I want the site in European Portuguese with Portuguese number and date formats, so that it reads as made for Portugal.
43. As a search engine, I want canonical URLs, sitemaps, structured data for offers and articles, OpenGraph images and noindex on expired promotions, so that pages rank and previews look right.
44. As Miguel, I want cookieless Cloudflare Web Analytics and per-promotion affiliate `sub_id`s, so that I know which pages bring visits and which promotions bring clicks without a cookie banner.
45. As Miguel, I want the new site to replace the current one on the same Cloudflare Pages project with no broken URLs, so that nothing already shared stops working.
46. As Miguel, I want the site to build from committed fixture data without the Python pipeline, so that the website can be developed and tested independently.

### Content (M4)
47. As Miguel, I want itineraries and tips as MDX files with front matter and a `reviewed` flag, so that nothing I have not read goes live.
48. As Miguel, I want Claude to draft an itinerary for each destination that has had a published promotion, so that content grows where there is demand.
49. As Miguel, I want each itinerary to include affiliate blocks for eSIM, travel insurance and activities placed where they are relevant, so that itineraries earn as well as inform.
50. As Miguel, I want a pt-PT content lint (no "você", no Brazilian spellings, Portuguese formats) run in tests, so that language mistakes are caught before review.
51. As a visitor, I want itineraries that state when facts were last checked and link to official sources for prices and opening hours, so that I can trust them.
52. As Miguel, I want the old YAML "guia rápido" converted to the new tips format, so that there is one content system.

### Distribution (M5)
53. As Miguel, I want nothing published to Instagram, Telegram or anywhere else without my approval, so that I remain responsible for what carries the brand.
54. As Miguel, I want approved promotions placed in a posting queue with fixed daily slots (default 09:00, 13:00, 19:00 Lisbon, max 3/day), so that the feed never looks like a bot dumping deals.
55. As Miguel, I want a queued promotion that expires before its slot removed from the queue automatically, so that we never post a dead deal.
56. As Miguel, I want approved promotions published to Instagram as a carousel (JPEG slides from the public site) plus a story with the cover slide, with the publishing limit checked first, so that the main channel runs itself after my approval.
57. As Miguel, I want the long-lived Instagram token refreshed automatically before it expires, so that publishing does not silently stop after 60 days.
58. As Miguel, I want approved promotions posted to a Telegram channel immediately (with the affiliate link), so that subscribers get deals in real time.
59. As Miguel, I want a ready-to-paste WhatsApp text for each approved promotion shown in the review UI with a copy button, so that I can post to WhatsApp manually in seconds.
60. As Miguel, I want the published post URLs stored on the promotion, so that the site can link to the Instagram post and I can audit what went out.

### Brand (M6)
61. As Miguel, I want a guided checklist (name decision, `.pt` registration, Cloudflare custom domain, redirects from `.pages.dev`, Travelpayouts project for the site, Instagram bio), so that the brand switch is one afternoon's work with nothing forgotten.

### Operations
62. As Miguel, I want every ticket to start with an "Ações do Miguel" section listing exactly what only I can do, step by step, so that I am never blocked guessing.
63. As Miguel, I want README, CLAUDE.md, DECISIONS.md and GLOSSARY.md updated in the same commit as each change, so that the docs never lag the code.

## Implementation Decisions

### Repository and runtime
- **Monorepo.** Python pipeline stays where it is; the Astro site lives in a `web` package with its own `package.json`. The Python side writes versioned JSON data files into the web package; that JSON is the only coupling.
- **Hosting at zero cost:** GitHub Actions (cron every 2 h, plus `workflow_dispatch`/`repository_dispatch` for on-demand runs) for compute; Cloudflare R2 for the SQLite database, raw archives, review events and backups; Cloudflare Pages for the site and the review Function. A GitHub Actions concurrency group plus an R2 lock object prevent overlapping runs. Fallback if R2 cannot be enabled without a card and Miguel declines: database in the Actions cache with a weekly snapshot as a GitHub Release asset, behind the same storage interface.
- **Object storage behind one interface.** A small `ObjectStore` abstraction (get/put/list/delete/with-lock) with an S3-compatible implementation for R2 and a local-directory implementation for tests and for Miguel's PC. The pipeline downloads the database at start and uploads at the end of a run; daily backup objects expire after 30 days via a lifecycle rule.
- **Secrets** stay in `.env` locally, GitHub Actions secrets in CI and Pages environment variables for the Function. `.env.example` lists every new key (R2 endpoint/key/secret/bucket, GitHub dispatch token, Telegram bot token/channel, Instagram token/account id).
- The Windows scheduler scripts remain until the Actions pipeline has a clean week; the README documents the unregister command.

### Routes
- New `routes` table replaces the static route list as the source of truth: origin airport, destination (provider city code), destination airport(s), Portuguese city name, kind (`europe`, `long_haul`, `domestic`), rule overrides (`direct_only`, `min_nights`, `max_nights`, `max_transfers`), `status` (`active`/`dormant`), `discovered_at`, `last_observed_at`.
- Discovery = provider's static route catalogue (airline routes with zero transfers) filtered to the six origins, airports mapped to city codes and Portuguese names via the provider's city/airport catalogues; supplemented by the provider's "popular directions from a city" endpoint. Runs monthly (and on demand). Config keeps: origin list, the long-haul destination list with its rule set, exclusions, per-kind defaults, and photo query overrides.
- Lifecycle: `active` → `dormant` after 30 days without observations; discovery reactivates. No deletion.
- Collector loops over active routes with each route's own nights range; the detector enforces `max_transfers` per direction for long-haul routes and `direct_only` for the others.

### Observations and archives
- Observation identity for deduplication: (source, origin, destination, departure_at, return_at, airline, flight_number, price, found_at). A repeated observation updates `last_seen_at`, `last_run_id` and `seen_count`; `run_id` keeps the first run. Schema migration bumps the user version and backfills existing rows.
- `raw_json` leaves the hot table: each run archives all responses as one gzip JSON object keyed by run id; the run row stores the archive key. Traceability chain: rendered price → promotion → observation → first run → archive object.
- `found_date` (local) remains the day key for baselines and freshness (D11/D12 unchanged).

### Detection, tiers and expiry
- Baseline unchanged: typical low = median of daily lows per route and departure month, `min_baseline_days` as today.
- Two outputs per run: **low prices** (fresh observations ≥ `low_threshold` below the typical low, default 15 %, exported for the site, never reviewed) and **promotion candidates** (≥ `threshold` 30 % and ≥ `min_saving_eur` 15 € below, one per route per run, deduped over 7 days) which become deals in status `new`.
- Promotion statuses and transitions stay as in the review module (`new → rendered → approved → published`, `rejected`, `expired`), plus the posting queue state described under Distribution.
- The traceability test renders the site and every caption and checks each price string against the set of observation prices for the referenced ids.

### Review from anywhere
- The pipeline exports a `review snapshot` (open queue, approved, recent published/closed, with slide URLs on the public site, WhatsApp text, live-check data) to object storage after each run.
- The review Function (Cloudflare Pages Functions, TypeScript) serves the queue from the snapshot and writes **review events** (`approve`, `reject`, `published`, with note, actor e-mail from the Access header, timestamp) as individual objects. It performs the live price check against the provider on approve (same rule as today) and, on success, fires a `repository_dispatch` to GitHub so the pipeline applies events within minutes. It is only reachable through Cloudflare Access (Miguel's e-mail); the Function refuses requests without the Access assertion header.
- The pipeline applies pending events idempotently at the start of each run (re-verifying the transition against the current status), then archives them. The CLI `deal` commands write the same events rather than touching the database directly, so terminal and phone share one log.

### Website
- **Astro (static output) + Tailwind**, content collections for itineraries and tips (MDX, `reviewed` front matter gates publication), pt-PT only. The design system (M2) is applied through Tailwind tokens and a small component set; no CSS framework defaults leak through.
- **JSON data contract** (versioned, JSON Schema in the repo, validated on both sides): origins, routes (with monthly typical lows and averages, status, counts), promotions (live and recently expired, with image URLs), low prices (per origin, date level, for the explorer), destinations, build metadata. Committed fixture data lets the site build and test without Python.
- The explorer is a client-side island over the per-origin low-price JSON (no backend). Weekend = departure Fri/Sat and return Sun/Mon. **Pontes**: a Portuguese holiday calendar (2026–2027) in the repo defines each long weekend's date window; the explorer filter and the per-ponte pages select low prices whose departure and return fall inside the window.
- Pages: home, promotions list, promotion page, route page, origin page, destination hub, explorer, ponte pages, itineraries, tips, about, privacy, contact, 404; sitemap and robots; JSON-LD (`Offer`/`Trip` on promotions, `Article` on content). Existing promotion URLs (`/promos/<id>-<slug>/`) are preserved or redirected via `_redirects`.
- Aviasales search widget embedded via the partner script with our marker, lazy-loaded below the fold on route and destination pages only. Cloudflare Web Analytics beacon when a token is configured.
- Images: slides as WebP for the site and **JPEG** copies for Instagram; thumbnails and OG images as today.
- Deploy unchanged in principle (wrangler Direct Upload to the existing project, skipped when the content hash is unchanged) but driven from Actions; `base_url` switches to the final domain in M6.

### Design process
- Three directions as static HTML pages (home + promotion page each, real data, real photos), reviewed in the browser; the choice and the resulting tokens are written to a design-system document and to `DECISIONS.md`. Slide templates (Jinja/Playwright) adopt the same tokens. Provisional logo = typographic SVG mark in the repo.

### Content
- Itinerary template front matter: destination code, title, days, best months, last-checked date, sources, affiliate blocks. Tips template: topic, last-checked date, sources. Both default `reviewed: false`.
- Affiliate blocks are components rendering tracked links for the programmes Miguel joins in Travelpayouts (eSIM, insurance, activities); the programme/marker configuration lives in config, not in content.
- The pt-PT lint is a word/pattern list test over all content and templates.

### Distribution
- **Posting queue** table: deal id, channel (`instagram`, `telegram`), scheduled slot, status (`queued`, `published`, `cancelled`), result URL. Approval enqueues Instagram at the next free slot (configurable slots and daily cap) and Telegram immediately. Each run publishes due items after re-verifying the promotion; expired promotions cancel their queue entries.
- **Instagram**: Instagram Platform with Business Login (no Facebook Page needed) unless Miguel's account is linked to a Page, in which case Facebook Login; carousel container of JPEG children hosted on the public site, caption from the existing caption module, then a story of the cover; publishing limit endpoint checked first; long-lived token refreshed when <10 days remain and written back to the secret store Miguel is guided to update.
- **Telegram**: Bot API `sendPhoto` with caption and the affiliate link to the channel.
- **WhatsApp**: text generated alongside the caption (shorter, link included) and exposed in the review snapshot.

### Milestone gating
- M6 (name/domain) is a hard gate for the M3 go-live: the new site launches on the final domain with redirects from `.pages.dev`.

## Testing Decisions

What makes a good test here: it exercises a whole behaviour through a public entry point (a pipeline step, a build, an HTTP handler) with real storage in a temp location and the network mocked, and asserts on outputs a user would see (rows, files, HTML, requests sent) rather than on internals.

Seams (preferring the existing ones):

1. **Pipeline seam (existing).** `pipeline.run_*`, build/export and review actions over a temporary SQLite database with the provider's HTTP mocked by `respx` and recorded fixtures. Prior art: `test_pipeline.py`, `test_review.py`, `test_website.py`. Used for: route discovery (recorded catalogue fixtures), per-kind rules, long-haul transfer rule, dormancy, deduplication and archive keys, two tiers, event application, posting queue, Instagram/Telegram publishers (HTTP mocked), WhatsApp text, JSON export validated against the schema, traceability test.
2. **Object store seam (new).** The `ObjectStore` interface with the local-directory implementation in tests; one contract test suite runs against both implementations (the S3 one against a mocked endpoint). Review events, snapshots, archives, backups and the lock are all tested through it.
3. **Web data contract seam (new).** The JSON Schema is the shared contract: Python tests validate exports against it; the web package validates fixtures and builds from them. Web tests (vitest) run `astro build` on fixture data and assert on the generated HTML (links resolve, prices present, noindex on expired, JSON-LD valid, pt-PT lint). Lighthouse CI runs against the built fixtures on pull requests with the ≥ 90 thresholds.
4. **Review Function seam (new).** The handler is a pure function of (request, bindings) tested with vitest against an in-memory bucket stub and a mocked provider; tests cover Access header enforcement, event shape, live-check refusal, and the dispatch call.

Pure modules keep their unit suites (`test_detector.py`, `test_recheck.py`, captions, i18n), extended for per-route rules, `min_saving_eur`, the low-price tier, weekend/ponte classification and the holiday calendar.

No test touches the network or Miguel's accounts. Fixtures are recorded once from real responses and committed.

## Out of Scope

- Hotels, packages (flight + hotel), car rental deals, trains, news articles.
- Ads of any kind (revisit at > 10k visits/month).
- Newsletter (revisit at ≥ 10 itineraries), WhatsApp automation, Pinterest, TikTok.
- GA4 or any cookie-based analytics; cookie banner.
- Live price search of our own (we only link to the partner's live search).
- The final name, the `.pt` purchase and the designer-made logo themselves (M6 provides the guided checklist and the technical switch; the decisions are Miguel's).
- Paid hosting of any kind.

## Further Notes

- Travelpayouts facts verified 2026-10-13: static route catalogue and city/airport catalogues exist and are public; the "popular directions from a city" endpoint works with the project token; `prices_for_dates` limit is 600 req/min, so ~300 routes × 3 months per run is well within budget.
- Observed volume at 10 routes: ~5.8k rows/day without deduplication; the deduplication decision is required before scaling, independent of hosting.
- Free-tier budgets to monitor (documented in README with the commands to check them): GitHub Actions 2000 min/month for a private repository (fast path ≈ 1–2 min × 12/day); R2 10 GB storage and 1M class-A operations/month; Workers/Pages Functions 100k requests/day.
- Deferred decisions carried to tickets: whether Miguel's Instagram account is linked to a Facebook Page (selects the Meta login flow); whether R2 can be enabled without a card (selects storage fallback).
- Open items for Miguel from v1 remain in `LAUNCH_CHECKLIST.md` (payout method, Instagram bio link, review of "Como funciona"/"Privacidade" copy, Travelpayouts project for the site).

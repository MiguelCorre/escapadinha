# CLAUDE.md

Travel-deals pipeline for the Portuguese market: collect → detect → render. Approved promotions are queued for posting (D32): Instagram
through the Graph API when its secrets are set (D36), Telegram through the Bot API likewise (D38).
See README.md for usage and DECISIONS.md for rationale and the roadmap. Vocabulary: GLOSSARY.md.
v2 work is tracked as GitHub Issues (spec #1, tickets #2–#24): conventions in docs/agents/.

## Commands
- `uv run pytest`: all tests. `-m "not browser"` skips the Playwright render test.
- `uv run escapadinha <cmd>`: CLI (`init-db`, `collect`, `recheck`, `detect`, `stats`, `routes list|discover`, `photos fetch`,
  `render deals|guide`, `run [--full]`, `review`, `deal check|approve|reject|published`, `queue list|retry`,
  `instagram token`,
  `site build|preview|setup|deploy|crawl|build-jinja`, `design directions`, `export site-data|fixtures`,
  `store status|pull|push|restore|upload-archives|check`).
- Set `PYTHONIOENCODING=utf-8` in Git Bash on Windows so pt-PT output prints correctly.
- Web package (`cd web`): `npm ci`, `npm run typecheck` (strict tsc: `tsconfig.functions.json`
  without Node types, `tsconfig.typecheck.json` for `src/lib` + tests), `npm test` (vitest builds from the fixtures), `npm run
  build:fixtures` / `dev:fixtures` (the build on a checkout), `npm run build` (reads
  `SITE_DATA_DIR`, default `web/src/data`; fails on purpose until `escapadinha export site-data`
  fills it; `escapadinha site build` does npm ci + build + images + routing), `npm run lhci`,
  `npm run tokens`. `npx vitest run test/review` runs only the review Function's tests.
- Scheduler Worker (`cd workers/scheduler`, no dependencies): `node --test` (`uv run pytest` runs it
  too); deployed by hand only, `npx --yes wrangler@4.149.0 deploy` (D41, `docs/runbooks/agendamento.md`).

## Rules
- **Never fabricate prices.** Observations come only from API payloads. No seed/demo data
  outside tests (tests use `tmp_path`). Every deal must trace to `price_observations.id`.
  Every element on the site that shows a price carries `data-obs`, `data-deal` or `data-route`;
  `tests/test_traceability.py` fails on any price string on a page or caption it can't trace.
  In the website JSON (`contract/site/v1`, D27) every price is an `eur` field next to its
  observation id, route key or deal id; a new price field must be taught to the checker in
  `tests/test_site_data.py` (a guard fails otherwise).
- The Astro site in `web/` (D28) reads only the contract JSON from `SITE_DATA_DIR` (default
  `web/src/data`, git-ignored; tests and Lighthouse CI use `contract/site/v1/fixtures`) and
  validates it against the schemas at build time; never import Python output any other way.
  Every price element carries `data-obs`/`data-deal`/`data-route`
  (`web/test/traceability.test.ts`), booking buttons only via `src/lib/cta.ts` (live + https link,
  with `labels.disclosure.site`), low-price rows only via `src/lib/low-prices.ts` (route pages,
  explorer, ponte pages and the island share it; no link yet → `NO_LINK_NOTE`), expired promotions `noindex` without a button (for `site.expired_promotions_days`, then a 301 to their route page, D35), pt-PT formats (every month/weekday
  word, price, date and trip text) only from `src/lib/format.ts` and day arithmetic only from
  `src/lib/dates.ts` (`web/test/format.test.ts` fails on month or weekday names elsewhere), copy passes `web/test/pt-lint.test.ts`. Styles use only the generated
  tokens (`src/styles/tokens.css` for CSS, `src/lib/tokens.ts` `TOKENS` for code; `npm run tokens`;
  `tests/test_web_tokens.py` catches drift); `web/test/colours.test.ts` fails on any raw hex or
  rgb()/hsl() colour elsewhere in `web/src/` or `web/functions/`.
- Itineraries and tips (D33) are MDX in `web/src/content/{itineraries,tips}/` (file name = slug,
  pages `/roteiros/<slug>/`, `/dicas/<slug>/`), front matter per `src/lib/content.ts`. Only
  `reviewed: true` is built or listed, and only a human sets it (never mark Claude's drafts
  reviewed); a reviewed entry needs `last_checked` and an official https source. Pages, listings,
  itinerary links read entries only through `src/collections.ts` (the
  gate); drafts show in `astro dev` only. A fixture build builds the real reviewed entries too;
  there a test-only itinerary wins over a real one for its city (`itineraryFor`), and the fixture
  export links only test-only articles' affiliate blocks: approving real content must never break
  the fixture build, a web test or the committed fixtures (tests read real entries from the files). No prices in content: no "€"/"EUR"/euro amounts (the
  pt-PT lint over all MDX refuses them, plus pt-BR words, "3.5", ISO/English dates, "20 %");
  prices come from the contract with their `data-obs`. Test-only entries (`fixture: true`) live
  in `web/test/fixtures/content/` and are built from fixture data only.
- SEO on the Astro site (D34): a page decides its own `noindex`; `sitemap.xml` is generated from
  the built pages (`src/lib/sitemap.ts`), never from a list. JSON-LD only through
  `src/lib/structured-data.ts` (schema-dts types; add the type's JSON Schema to
  `web/test/jsonld.ts`) and `JsonLd.astro`/`Breadcrumbs.astro`; a block with a price carries its
  `data-obs`/`data-deal` (the traceability test checks JSON-LD too); no Offer on an expired
  promotion. Third-party scripts only from the contract's `meta`: the Cloudflare beacon only with
  `analytics_token` (null: the zone's automatic setup measures at the edge), the Aviasales search
  form only with `search_widget` (from Travelpayouts' widget constructor, never hand-built; read it
  through `Context.search_widget()`, which checks its `trs` and `shmarker` are ours; route
  and destination pages only, loaded by `src/lib/search-widget.ts` only when the visitor presses
  its button: never on scroll or view, the privacy page promises it). Fixtures keep both
  null. The site sets no cookies (no `document.cookie`, no Set-Cookie).
- The review Function (D29, `web/functions/`, TypeScript) is a writer of pending review events
  only: it never changes a status (the applier does, D26). Every request must pass
  `access.verifyAccess` (RS256 Access JWT: signature against the team's certs, `aud` =
  `ACCESS_AUD`, `iss`, `exp`; the pages.dev host is not behind Access, so the header's presence
  proves nothing). Keep `handler.handle(request, env, deps)` pure (clock, fetch, UUIDs, key cache
  injected) and tested in `web/test/review/` on the in-memory bucket. Its live check is a port of
  `pipeline.price_now` + `recheck.recheck`: change both sides together and keep
  `contract/review/v1/fixtures/live-check-cases.json` passing on both (`tests/test_live_check_cases.py`,
  `web/test/review/live-check.test.ts`). Its decision rules port `review.py` (`TRANSITIONS`,
  `STATUS_PT`, `DECISIONS`, `DECISION_PT`, `check_decision`) and `db.OPEN_STATUSES`: change them
  with `contract/review/v1/fixtures/review-rules.json`, which `tests/test_review_rules_cases.py`
  and `web/test/review/rules.test.ts` check on both sides. Function sources import only relative modules under
  `web/functions/` or `web/src/lib/` (no npm packages: wrangler bundles them without
  `node_modules`; `deploy.function_files` refuses a package import); wrangler runs in `web/`
  (D35), and both the deploy hash and `run_path._code_files` include them.
- The website data contract is versioned: change `contract/site/v1/*.schema.json` together with
  `site_data.py`, keep changes additive within v1 (a breaking change is `v2/`), and regenerate the
  committed fixtures with `escapadinha export fixtures` (read-only DB copy, anonymous links and
  credits). Fixtures are test data (`meta.fixture: true`), never deployed.
- Two tiers (D24): **low prices** (`low_threshold`, automatic on route pages, mature baseline
  only) and **promotion candidates** (`threshold` AND `min_saving_eur`, become deals for review).
  Only candidates create deals; the home page shows promotions only.
- Mature typical lows (D40): a daily low counts only if that day saw `min_dates_per_day`
  departure dates; low prices and every typical low the site shows need `min_baseline_days`
  (`detector.is_mature`), promotion candidates `min_baseline_days_promo` spanning
  `min_baseline_span_days` (`detector.is_mature_for_promotions`; else only a route's
  `price_cap_eur`). All from config `detector`, passed in. A deal stores its baseline's span and
  the observation ids of its cheapest/dearest daily low (`pipeline.baseline_range`); the review
  snapshot and both review pages show them, each price on its `data-obs`. Every run, after
  detection, `pipeline.run_reevaluate` judges each deal awaiting review (`db.AWAITING_REVIEW`)
  again against its month's current typical low and rules (`recheck.promotion_expiry` =
  `detector.evaluate`, data passed in) and expires the ones that would not be detected now:
  pipeline-owned like the recheck's expiry, never an approve/reject; approved deals only get the
  price recheck.
- Every deal caption and CTA slide carries `presentation.DISCLOSURE`. Tests assert this.
- `detector.py` stays pure (no I/O, no clock). Pass `now` in. Route rules (`RouteRules`) are
  passed in too; never read a global `direct_only` or nights range. The same for the collector
  (`PriceSource.fetch(…, rules=)`): the provider query comes only from
  `travelpayouts.request_params(…, rules)` (`direct=true` on nonstop-only routes, D39), shared
  by the collection, `pipeline.price_now` and the snapshot's `live_check.query` (cases
  `queries` in `contract/review/v1/fixtures/live-check-cases.json`, checked on both sides).
- Routes come from the `routes` table via `routes.py` (`active_routes`, `get_route`), never from
  config. config.yaml only holds per-kind defaults, overrides, exclusions, long-haul list, seed,
  discovery origins and `city_names`. Discovery (`discovery.py`) is pure; its downloads live in
  `collector/catalogue.py`. Routes are never deleted: they go `dormant` (D23).
- Plain SQL in `storage/db.py`. Schema changes bump `SCHEMA_VERSION`, update `schema.sql` (fresh
  installs) and add the ALTER steps to `MIGRATIONS` (existing DBs; a step may be a Python
  callable). Test the upgrade from real old schemas (`tests/fixtures/schema_v5.sql`, `schema_v7.sql`).
  Pipeline bookkeeping (e.g. last discovery time) goes in the `meta` key/value table.
- Observations are deduplicated (`dedup_key`); never assume one row per run. Use
  `observations_seen_since(run_id)` for a run's prices (detection, recheck) and
  `pipeline.latest_offers` for the newest prices of every route-month (the site export: months
  4–6 come from the latest daily pass, D42). Raw payloads live only in the run archive
  (`archive.py` via `ObjectStore`), never in the hot table.
- What a collection run asks for (D42) is decided only by `collector/plan.py` (pure:
  `daily_pass_due` with `now` passed in and Lisbon days, `plan` → `Plan`); `runner.collect` runs
  a `Plan`. The day's pass (first run at or after `collector.daily_pass_hour` each Lisbon day,
  meta `collector.daily_pass`, recorded by `pipeline.run_collect` unless every request failed)
  asks every active route for `daily_months_ahead` months; other runs ask only routes with a
  `last_observed_at` for `months_ahead` months, plus the far month of every open promotion (the
  recheck judges every open deal on every run). Dormancy never judges a route the run didn't ask
  for (`mark_dormant(spare=)`).
- Objects go through `ctx.object_store` (R2 when the `R2_*` keys are set, else `data/objects/`);
  never write the bucket or `data/objects/` directly. Every `ObjectStore` implementation passes
  `tests/test_objects.py` (S3 runs on moto, no network). The database file is only uploaded via
  `storage/sync.py` (backup-API snapshot under the run lock), never the live file (D21).
- CI keeps no files between runs (D21, D25). Anything a run needs from an earlier run lives in the
  database (`meta`: `site.paths` (+ `site.paths.pending` between build and deploy), `site.links`,
  `site.deployed`, `site.link_budget`, `site.article_links`, the run-path fingerprint,
  `collector.daily_pass`) or goes
  through a `storage.mirror.Mirror` (`pipeline.photo_files` / `output_files`): upload when made,
  `file`/`folder` to read (downloads when missing). Never read `output/` or `assets/photos/`
  directly; use `pipeline.deal_folder` / `guide_folder` (pass `files=` the glob you read, e.g.
  `pipeline.SLIDES`, so a runner downloads only those, once), `deal_slide_names` (names only, no
  download), `deal_view` (its photo).
- The schedule (D41): `pipeline.yml` has no `schedule`, so every run of it is a real run. The
  Worker `workers/scheduler/` (Cron Trigger every 2 h, window 45 min) and
  `pipeline-fallback.yml` (GitHub's cron every 6 h, window 3 h; its job fails on purpose when it
  dispatches, so GitHub e-mails) both run `src/schedule.js` `tick`: skip a disabled workflow or
  a run created within the window, else dispatch `full: false`. Keep `Worker window + 2 h <
  pipeline.RUN_GAP_WARNING ≤ fallback window` and the vars equal to the fallback's env
  (`tests/test_scheduler.py`). The GitHub token (`GITHUB_ACTIONS_TOKEN`, fine-grained, Actions:
  read/write) is only a Worker secret, never a var; every log line and error goes through
  `redact`. The Worker stays plain JS without npm packages or a URL, deployed by hand with the
  pinned wrangler (the pipeline's Cloudflare token is Pages-only).
- `run` order (`cli._run_steps`): `apply_review_events` (D26) → late-run warning (D41, previous
  collection > 3 h ago) → upkeep → collect (the day's pass when due, D42) → recheck →
  detect (+ `run_reevaluate`, D40) → `publish_due` (D32, every run: posting never waits for a full path) →
  `run_path.decide` → full path only, its Node commands inside one deadline
  (`node.deadline()`, D35) (render → `export site-data` (D27, → `web/src/data`; keep the
  returned `Export`) → `site build` (Astro, D35: npm ci if needed, astro build, promotion images,
  `_redirects`/`_headers` → `web/dist`; the paths it implies go to `site.paths.pending`) →
  `site deploy` (`web/dist` + Functions; refuses a fixture build; on success, or skipped as
  unchanged, commits the pending paths) → `record_full_path(ctx, conn, export)`: the export that
  went live, never a re-read) → `export_review_snapshot` on every run, even a failed one. The
  full path runs only when `run_path.decide` says so. Anything new the site shows must be part of
  `run_path.fingerprint`, or a routine run won't publish it: the exported contract is (component
  `site_data`, minus the per-run fields `site_data.PER_RUN` lists and `site_data.shown_digest`
  drops: never render one of those on a page; a new field that changes every run must be
  classified there, `test_every_field_a_new_run_changes_is_classified_per_run` fails otherwise), and
  so are the web package's sources (`run_path.web_source_files`).
- Public deals, page slugs and image paths come from one place (`website.is_public`,
  `public_deal_rows`, `promo_slug`, `route_slug`, `origin_slug`, `destination_slugs`,
  `promo_image_dir`, `deal_image_paths`): the site, the site data export and the review snapshot
  all use them. The web package never builds a page path: it uses the contract's `path` fields.
- Captions must distinguish `found_date` (when a traveller saw the price) from `fetched_at`,
  and always name the arrival airport (remote ones in the headline).
- pt-PT formatting lives in `i18n_pt.py` (no OS locale). Times are shown in Europe/Lisbon.
- No scraping of booking sites or airlines (ToS and legal risk; see DECISIONS D13).
- Never publish a deal whose status is `expired` (recheck runs every collection). The website
  only shows deals a human approved; expired promotions stay `noindex` without a booking link
  for `site.expired_promotions_days`, then 301 to their route page (D35).
- Review decisions (approve, reject, published) are events (D26): writers (`pipeline.approve` /
  `reject` / `mark_published`, the review page, the review Function) only write
  `review/events/pending/`; `review_events.apply_pending` is the only code that changes those
  statuses (`tests/test_review_events.py` checks it). Approve needs a passing live check in the
  event (`pipeline.price_now`, stores nothing); the applier re-checks every transition, refuses
  approvals whose check is older than `review.approve_max_age_hours` (passed in as
  `approve_max_age`), and archives refused ones with a reason, never raising. Shapes: `contract/review/v1/*.schema.json`; change
  them only with a new version, except optional fields a reader can do without (D29's
  `transfers`, D40's `baseline`: the Function handles their absence, and the new `*_eur` field is
  taught to `test_review_events.SNAPSHOT_PRICES`). Render (new → rendered), rechecks and the
  queue's re-evaluation (D40) stay pipeline-owned.
- Posting queue (D32, `posting_queue`): only an applied approve event queues posts, in the
  applier's transaction (`plan_posts` passed into `apply_pending`). Slot rules stay pure in
  `posting.py` (`next_slot`, `verdict`; `now` passed in, Lisbon days). Channels are named only in
  `posting.CHANNELS` (the SQL CHECK is tested against it). A post goes out only from
  `pipeline.run_publish`, after re-verification; expired/rejected promotions cancel their posts.
  Publishers implement `posting.Publisher` (a story too: `posting.StoryPublisher`) and never
  change a review status (a real one returns `Published(marks_published=True)` and `run_publish`
  calls `pipeline.mark_published`); they signal `PublishWait` (no attempt counted) /
  `PublishCancel` / any other error (retried), read through `posting.attempt`. A real publisher
  that can't post (no secrets, no token) waits, never falls back to a dry run that would settle
  the post. Story states only from `posting.StoryStatus` (SQL CHECK tested against it). Post
  texts: the caption (Instagram) and `captions.whatsapp_text` (stored partner link +
  `DISCLOSURE`; Telegram), never a hand-built link. A real publisher without its secrets is
  `posting.Paused` (Instagram's own `instagram.Paused`), never the dry run.
- Publishers are registered only in `pipeline.PUBLISHERS` (name → `PublisherKind`: `build`
  from a `PublisherSetup`, `notices` for `queue list`; tested against config's `PublisherName`).
  Both real publishers check the site's JPEGs through `website.image_problem` +
  `posting.live_images` (wait, bounded), redact tokens with `posting.redact`, and signal a
  counted retry with `posting.RetryableSendError`.
- Telegram publisher (D38, `telegram.py`): Bot API `sendPhoto` only through `BotApi` (host
  `config.TELEGRAM_API`; the token is in the URL path: errors by type only, any text redacted,
  never a log, the database or CI output; httpx logs URLs at INFO, so never turn that on);
  `chat_id` is `TELEGRAM_CHANNEL`, checked by the factory (`telegram.channel_problem`: @handle
  or numeric id; malformed → Telegram paused with a notice, never a stopped run). Photo
  = the cover of `website.public_jpeg_urls`, caption = the post's text, never cut (over 1024
  UTF-16 units: cancel). Before the request a record goes to the object store
  (`telegram.record_key`), after it the message id: a send whose answer was lost
  (`NoAnswer(sent=True)`, or a record without an id) is cancelled, never resent by itself; only
  Miguel's `queue retry` (a request in the record, applied by `telegram.apply_retries` in
  `run_publish`, D26-style) requeues it. A refused channel or token waits with a notice (never
  cancels: no post lost to setup); errors are classified only in `TelegramPublisher._signal`
  (`CHANNEL_SETUP`, `PERMANENT`, `TRANSIENT_PHOTO`, from the Bot API's texts). Message id on the
  row (`message_id`, v12), its link in `result_url` (shown by `queue list` and `deal check`). It
  never marks a promotion published (that would cancel its Instagram post).
- Instagram publisher (D36, `instagram.py`): the Graph host only from `config.GRAPH_HOSTS` via
  `InstagramConfig.host`, the version from `api_version` (`Graph(http, api, token)`); images only
  `website.public_jpeg_urls` (HEAD 200, https redirects followed, else wait, bounded by
  `images_wait_hours`); poll every child and the carousel container to FINISHED; store every
  container/media id and the first attempt's caption with `db.save_post_progress` as soon as
  known, and check the account's latest posts by that stored caption before creating a
  carousel: a retry must never post twice; a story never reposts its carousel. Code 190 on any
  call waits and leaves a notice (`token_state`). The token never reaches a log, an error
  message (`Graph` redacts it), the database or CI output: a refreshed one lives only at
  `instagram.TOKEN_KEY` in the object store, meta `instagram.token` holds its fingerprint and
  expiry. HTTP in tests: respx only, no real call.
- Affiliate links only from `affiliate.PartnerLinksClient` (Travelpayouts API). Never build
  `marker=` URLs by hand, because Aviasales term 1.4 forbids it. Pick the Project with
  `affiliate.project_for("instagram"|"website")`; never read `project_id` directly (D19).
  Low prices' links go through `pipeline.low_price_links` (created once, stored in
  `partner_links`, capped per collection run, export + build together, by
  `site.max_new_links_per_build`).
- Affiliate blocks (D37: `<EsimBlock />`, `<InsuranceBlock />`, `<ActivitiesBlock />` in MDX): the
  programme → brand/page map lives only in config `affiliate.programmes` (`ProgrammeConfig`; a new
  programme is a config change, never code). Which (article, programme) pairs get a link is
  `pipeline.block_targets` only; links only via `pipeline.article_links` (website Project, sub_id
  `roteiro-<slug>`/`dica-<slug>`, meta `site.article_links`, pruned to the current pairs and
  Project on every write), exported in `affiliates.json`. `articles.py` reads the front matter
  exactly as the site does (zod + Astro's YAML): change either side together with
  `web/test/fixtures/content-gate-cases.json` (`tests/test_affiliate_blocks.py`,
  `web/test/content.test.ts`); the article key is `content.articleKey` / `Article.key`. On the
  site only through `src/lib/affiliates.ts` (`affiliateBlock`, link via `cta.partnerLink`) and
  `AffiliateBlock.astro`, always with `labels.disclosure.affiliate`; a programme not configured
  or a missing link renders nothing and warns, a block not listed in front matter fails the
  build. Every Astro build is `astro build --force` (`npm run build`,
  `build:fixtures`, `test/build-site.ts`): Astro's content cache ignores schema changes in
  `src/lib/content.ts`.
- Domain moves go through `site.base_url` + `site.legacy_hosts` and the Bulk Redirect in
  `docs/runbooks/brand-switch.md`; Pages `_redirects` can't match hosts. Page paths need a stable
  key in `website/routing.current_pages` (`deal:`, `route:`, `origin:`, `destination:`) so renamed
  slugs get a 301 (`website/redirects.py`); old URLs of pages that left the site get a rule there
  too (expired promotions → route, `/guias/` → `legacy_path`); a rule only targets a built page
  (never another rule), and over Cloudflare's 2000 rules the build fails. Never let an old URL 404:
  `tests/test_crawl.py` crawls the old site's URLs on the real Astro build; `site crawl` the live one.
  Destination hubs (D30) keep their published slug: the site data export records
  `destination:<code>` paths in `site.paths` and `website.destination_slugs` reuses them; never
  derive a hub slug without that history.
- Secrets only via `.env` (`Secrets` in `config.py`). Never commit `.env`, `data/`, `output/`.
- Update README.md, CLAUDE.md and DECISIONS.md in the same commit as a feature.

## Layout
- `src/escapadinha/collector/`: `TravelpayoutsSource` (+ `RateLimiter`), `plan.py` (the day's pass,
  D42), `runner.collect` (runs a `Plan`), `catalogue.py`
- `src/escapadinha/discovery.py`: pure `Catalogue.from_payloads` + `discover` → `Found` routes with kind
- `src/escapadinha/routes.py`: `sync` (config → `routes` table), `apply_discovery`, `mark_dormant`,
  `all_routes`/`active_routes`/`get_route`
- `src/escapadinha/storage/objects.py`: `ObjectStore` + `LocalObjectStore` (`data/objects/`); `archive.py`: per-run raw archive
- `src/escapadinha/storage/s3.py`: `S3ObjectStore` (R2, conditional-write lock); `sync.py`: database
  pull/push, `run_session` (lock → pull → daily backup → push → unlock), restore, `store check`;
  `mirror.py`: `Mirror` (a local folder also kept under a store prefix: `photos/`, `output/`)
- `src/escapadinha/run_path.py`: fast/full decision (`decide`, `fingerprint` incl. `site_data_digest`,
  `record_full_path(ctx, conn, export)`: records the export the full path wrote, never a re-read)
- `.github/workflows/pipeline.yml`: `escapadinha run` on Actions, dispatched every 2 h (D41);
  `full` input or `repository_dispatch` → `--full` (D25). `pipeline-fallback.yml`: the schedule's
  fallback (D41)
- `workers/scheduler/`: the scheduler Worker (D41): `wrangler.toml` (cron, vars), `src/schedule.js`
  (`tick`, `settings`, `recentRun`, `redact`), `src/index.js` (the Worker's `scheduled`),
  `src/fallback.js` (the Actions fallback's entry, exit codes), `test/` (node:test); runbook
  `docs/runbooks/agendamento.md`
- `src/escapadinha/detector.py`: daily-low `baseline` per route+month (days with 2+ departure
  dates, cheapest/dearest daily low), `is_mature` / `is_mature_for_promotions` (D40), `evaluate`
  (candidates), `low_prices`, `detect_route`, `detect` (→ `Detection(low_prices, candidates)`)
- `src/escapadinha/pipeline.py`: DB wiring per CLI step (`run_discover`, `run_dormancy`,
  `run_missing_photos`, ...), plus review actions (`live_check`, `approve`, ...)
- `src/escapadinha/review.py`: status transitions + `check_decision`; `review_events.py`: event log (write,
  `pending`, `apply_pending`); `review_snapshot.py`: `review/snapshot.json` + `review/slides/`;
  `web.py` + `templates/review.html.j2`: the local review page
- `contract/review/v1/`: JSON Schemas of review events and the snapshot (the review Function's contract);
  `fixtures/live-check-cases.json`: live-check cases shared by the pipeline and the Function
- `src/escapadinha/renderer/templates/`: `base.html.j2` (tokens, fonts, scrims, components, fitText),
  `_ui.html.j2` (masthead, price block, dots, credit) + `deal/`, `guide/`
- `docs/design/`: `design-system.md` (the visual contract) + `tokens.json`, generated from
  `renderer/tokens.py` (`tokens.write_json()`; a test fails if stale or below WCAG AA). Fonts in
  `assets/fonts/` (OFL WOFF2), logos `assets/logo-light.svg` / `logo-dark.svg`.
- `src/escapadinha/captions/templates/`: `deal.txt.j2`, `guide.txt.j2`, `whatsapp.txt.j2`
- `src/escapadinha/posting.py`: posting queue rules (`CHANNELS`, slots, `verdict` →
  `VerdictAction`, `story_verdict`, `StoryStatus`) + the publisher protocol (`Publisher`,
  `StoryPublisher`, `Published`, `PublishWait`, `PublishCancel`, `attempt`, `DryRunPublisher`,
  `Paused`);
  DB wiring in `pipeline.run_publish` (`publishers_for`, `PostResult.action`: `PostAction`,
  stories in `_run_stories`), the queue read with `db.posts`
- `src/escapadinha/telegram.py`: `BotApi` (token redacted, `NoAnswer`/`BotApiError`),
  `TelegramPublisher` (send record, `_signal`), `message_link`, `unconfirmed`/`request_retry`/
  `apply_retries` (`queue retry`), `problem_state`/`notices` (meta `telegram.problem`); runbook
  `docs/runbooks/telegram.md`
- `src/escapadinha/instagram.py`: `Graph` (calls, token redacted), `classify` (Graph error →
  wait/cancel/retry), `InstagramPublisher` (carousel, story, limit,
  polling, `_reuse`/`_finish` resume), `Paused`, `ensure_token` (refresh, stored token),
  `token_state`, `notices`; runbook `docs/runbooks/instagram.md`
- `content/guides/*.yaml`: hand-written guide content (`reviewed: true` after fact check)
- `src/escapadinha/website/`: `astro.py` (`site build`: npm ci stamp, `astro_build`, `finish`),
  `routing.py` (`plan`/`write`: `_redirects` only to built pages, chains collapsed, fails over
  2000 rules; `commit`: the build's paths join `site.paths` only after the deploy),
  `node.py` (finds npm/npx/node, `run` with the full path's one deadline, `web_dir`/`dist_dir`,
  `BuildError`; light, so the CLI imports it at the top),
  `crawl.py` (`site crawl`: a sitemap against a build or the live site),
  `images.py` (promotion WebP/thumb/OG + JPEG slides for Instagram, D36), `redirects.py` (rules), `deploy.py` (wrangler in `web/`,
  `function_files`, `deploy_hash`, fixture refusal); `__init__.py` shares with the export
  `public_deal_rows`, `route_slug`, `promo_slug`, `deal_image_paths`, ... **Legacy until #23
  phase 2:** `SiteBuilder`/`build_site` + `templates/` (the Jinja site, `site build-jinja`, never
  deployed, not part of `run`); don't extend them, and don't read them as the site's rules (the
  Astro site in `web/` is the site).
- `src/escapadinha/pontes.py` + `content/holidays.yaml`: Portuguese holidays 2026–2027 and their
  long weekends (D31; pure `long_weekend`/`pontes`, exported as `pontes.json`, past ones too, raw
  values only). The ponte rule (departure and return inside the window) and the weekend rule
  live in `web/src/lib/explorer.ts` (explorer + ponte pages); titles in `format.ponteTitle` with
  the article from config `origins_article` (`origins.json` `article`), never a map in code
- `src/escapadinha/site_data.py`: website data contract v1 (`export_site_data` → `site.data_dir`,
  `generate_fixtures`); schemas + committed fixtures in `contract/site/v1/` (D27)
- `src/escapadinha/articles.py`: the MDX articles' front matter as the pipeline sees it
  (`published`: the review gate; `Article.key`, `sub_id`) for the affiliate blocks (D37)
- `web/`: the Astro site (D28): `src/pages/` (home, `promos/`, `voos/` route pages, `partidas/`
  origin pages, `destinos/` hubs, D30; `roteiros/`, `dicas/` D33; `sobre/`, `privacidade/`,
  `robots.txt` D34), view logic in `src/lib/`
  (`promotion.ts`, `routes.ts`, `low-prices.ts`, `format.ts` + `dates.ts`, `cta.ts`, `content.ts` +
  `itinerary.ts` + `related.ts`, `affiliates.ts` (blocks D37, components in
  `src/components/mdx-components.ts`); SEO D34: `structured-data.ts`, `sitemap.ts` (Astro integration),
  `search-widget.ts`),
  `src/content.config.ts` + `src/collections.ts` (MDX collections + review gate), tests in
  `web/test/` (fixture build + a configured build with fake analytics/widget values in
  `build-site.ts`, `scale.test.ts` full-size synthetic build, traceability, internal links,
  `content-pages.test.ts`, `seo.test.ts` + `jsonld.ts`, `seo-configured.test.ts`)
- `docs/runbooks/`: pt-PT step-by-step guides for things only Miguel can do (e.g. `brand-switch.md`,
  `search-widget.md`, `instagram.md`, `telegram.md`, `agendamento.md`, `rever-conteudo.md`: reviewing MDX drafts in `npm run dev:fixtures`)
- `web/`: the Astro site (own `package.json`, Node 22): `src/lib/site-data.ts` (load + ajv
  validation) behind `virtual:site-data`, `format.ts` (pt-PT), `promotion.ts` (view of a
  promotion), `cta.ts` (booking button + disclosure); `src/layouts/Base.astro`, `src/components/`,
  `src/pages/` (`index`, `promos/[slug]`, `404`, `og-default.png`); `scripts/tokens.mjs`;
  `test/` (vitest); `lighthouserc.json`; CI in `.github/workflows/web.yml`
- `web/functions/review/index.ts` + `[[path]].ts`: Pages routes `/review` and `/review/*`, both
  `serve` from `web/functions/_lib/review/`: `handler.ts` (routing, decisions), `access.ts` (JWT),
  `live-check.ts` (port of the recheck), `rules.ts` (port of `review.check_decision`),
  `events.ts` (event keys, pending, dispatch), `page.ts` (the queue HTML), `serve.ts` (runtime deps)
- `src/escapadinha/design_directions/`: M2 visual directions (`build_directions` → `output/directions/`);
  palettes + fonts in `directions.py` (contrast computed by `contrast.py`), read-only data in `data.py`

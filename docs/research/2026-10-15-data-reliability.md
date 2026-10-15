# Data reliability: more price points and safer promotion rules

*Research, 2026-10-15. Read-only: database copy `data/escapadinha.db` up to run 57 (2026-10-15 21:00 UTC),
opened `mode=ro`. 20 sample calls to the Travelpayouts Data API with our token (payloads kept out of
the repo). No code, config or store changes.*

Miguel's question: "Quero ter uma base de dados reliable, para não mandar deals que afinal não são assim
tão bons. Precisamos de ter mais dados do nosso lado."

## Recommendation

1. **Send `direct=true` to `v3/prices_for_dates` for the 320 direct-only routes (europe + domestic), in
   place of today's call.** The request count stays at 1080 per run. The cache returns **one offer per
   (departure date, return date) pair: the cheapest.** When the cheapest offer for a pair has a stop,
   the nonstop fare for that pair never reaches us, and these routes discard every offer with a stop.
   - **LIS-PAR, December, same minute:** the current call gave 8 nonstop trips out of 26 date pairs;
     `direct=true` gave 21 nonstop trips over the same 26 pairs.
   - **LIS-ROM, December:** one `direct=true` call gave 13 nonstop trips, 10 of them not in the
     database. Three days of collection had stored 6.
   - **In one call**, each of these two route-months went from 6 to 9 daily lows.
   - **Recheck:** the same fix stops false "a viagem já não aparece" expiries. Today a deal's nonstop
     fare drops out of the cache as soon as a cheaper fare with a stop appears for those dates.
   - **Expected:** about 2–3× the usable observations on direct-only routes. 57 % of the rows we store
     today are thrown away for having a stop (2165 of 3790 on direct-only routes).

2. **Make promotions wait for a mature typical low.** Required: **≥ 10 daily lows spanning ≥ 9 days**
   (today: ≥ 4 days, no span). A day counts only if **≥ 2 different departure dates** were seen that
   day. Low prices: **≥ 7 daily lows** (today: 4). Keep `threshold` 0.30, `min_saving_eur` 15 and the
   median.
   - **The evidence:** checked against everything we know now, **7 of the 11 deals so far were not
     30 % below the typical low.** Of the 6 deals waiting for review, only the two LIS-FNC ones hold.
   - **Bias:** the 4–6-day baselines overstated the discount in every case, by 7 points in the median.
   - **Cost:** for about a week there will be no promotion candidates. The busiest routes qualify
     first, from roughly 20–25 October. Thin route-months may never qualify before departure. That
     trade is what Miguel asked for.
   - **Low prices now:** 32 on 10 routes under today's rule, 5 on 2 routes at ≥ 7 days.

3. **Show the baseline to the reviewer.** Put the days, span and min–max of the daily lows next to
   each promotion on the review page and in the snapshot. Example: "típico 99 € (9 dias, 54–110 €)".
   With that, Miguel can see a 4-day baseline before approving. This needs no new data.

4. **Add departure months 4–6, but fetch them once a day, not every run.** Far months are thin in the
   cache: LIS-BCN had 10 / 2 / 2 offers for Jan / Feb / Mar 2027, against 24 for November. Their found
   days stay in the cache for about 7 days, so one pass a day misses little.
   - **Cost:** +1080 requests and about 2 min of one run per day. Running months 4–6 on every run
     would add the same on all 12 runs.
   - **Gain:** Christmas/New Year, Carnaval (2027-02-09) and Easter (2027-03-28) build a baseline 2–3
     months before they enter the promotion window. They would not start from zero.

5. **Keep a 2-hour cadence, and make it real.** The GitHub cron says every 2 h, but its scheduled runs
   came 5.5 h apart (median of 9, range 4.4–6.8 h). The 2-hourly runs in the database come from the
   PC's Windows task, which the README plans to unregister. Before that, put a reliable trigger in
   front of `workflow_dispatch` (for example a Cloudflare Worker cron), or accept roughly 5-hour data.
   - **Not hourly:** new data per hour is flat (11–19 new usable offers per hour), and nights are
     quiet.

6. **Don't add any other Data API endpoint.** They read the same 7-day user-search cache and returned
   no price point that both is absent from `prices_for_dates` and has a traceable search behind it.

7. *(Optional, frees requests for item 4.)* **121 of the 360 active routes (34 % of every run's
   requests) have never returned a price** in 57 runs. Dormancy only starts after 30 days (D23).
   Polling never-seen routes once a day would save about 360 requests a run.

Changing the request (item 1) touches `collector.travelpayouts.request_params`. The review snapshot
carries those params, and the review Function's live check asks with them (D26). So the change has to
go through `contract/review/v1/fixtures/live-check-cases.json` on both sides, plus README, CLAUDE.md
and DECISIONS.md (CLAUDE.md rules).

---

## 1. Other Travelpayouts endpoints

### What the docs say

All Data API methods read one cache built from searches on Aviasales sites: "Data is transferred from
the cache based on the user's search history from Aviasales websites. The data is stored for 7 days
for all types of queries" ([Aviasales Data API][dataapi]). Each search belongs to a market. We already
use `market=pt`.

| Endpoint | Returns | Found date | One price per day of the month? | Limit/min (docs; headers we saw) | Fits our observation model? |
|---|---|---|---|---|---|
| `aviasales/v3/prices_for_dates` (current) | Cheapest offer per (departure, return) date pair, with `link`, `transfers`, `return_transfers`, airline, flight number and airports. `limit` up to 1000. Recommended in place of `/v1/prices/cheap`, `/v1/prices/direct`, `/v1/city-directions` and `/v2/prices/latest`. | `search_date` in `link` (we parse it) | No: one per searched date pair | 600 ([rate limits][limits]); header `x-rate-limit: 600` | Yes (it is the model) |
| `aviasales/v3/get_latest_prices` | `value`, `depart_date`, `return_date`, `number_of_changes`, `found_at`, `gate`. `period_type` year/month/day, `beginning_of_period`, `limit`. **No link, airline, flight number, airports, or stops per direction.** | `found_at` timestamp | No | 300; header 300 | Weakly. Without a link it can never be a deal (D13). With only `number_of_changes` it can't apply `direct_only` per direction, and `dedup_key` loses airline and flight. |
| `aviasales/v3/grouped_prices` | Same item shape as `prices_for_dates`, cheapest per `departure_at` day (or per `month`). `min_trip_duration`/`max_trip_duration`. Replaces `/v1/prices/calendar` and `/v1/prices/monthly`. | `search_date` in `link` | **Yes, one per departure day**, but only the cheapest of that day | 600; header 600 | Yes, but it is a strict subset of `prices_for_dates` |
| `v2/prices/month-matrix` | "the prices for each day of the month, grouped together by the number of transfers". Same fields as `get_latest_prices`. | `found_at` | Yes (per departure day) | 300; header 300 | Weakly (same gaps as `get_latest_prices`) |
| `v2/prices/week-matrix` | Prices for −3/+4 days around a departure and return date | `found_at` | No (one week) | 60; header 60 | Weakly |
| `v1/prices/calendar` | Cheapest per departure day, `transfers` (outbound only), `expires_at` | **None** (only `expires_at`) | Yes | 300 (docs also say "10 requests per second"); header 300 | No: can't be placed on the found-date axis |
| `v1/prices/cheap` | Cheapest tickets for the month | **None** (`expires_at`) | No | 300; header 300 | No |
| `v2/prices/latest` | Old form of `get_latest_prices` ("last 48 hours") | `found_at` | No | 300 | Superseded by `prices_for_dates` per the docs |
| GraphQL `/graphql/v1/` | Same data through one query language | (per query) | (per query) | 60 | Not tested; same cache |

Sources: [Aviasales Data API][dataapi] (support article, updated 2026-09-06), [API rate limits][limits],
[slate API reference][slate], [GraphQL][graphql]. The support center blocks plain fetches, so the
articles were read through its public Help Center API (`/api/v2/help_center/en-us/articles/<id>.json`).

### What 20 sample calls showed (LIS-BCN and LIS-MLA, November 2026; `market=pt`, `currency=eur`)

LIS-BCN in November is a busy route. The calls were made within one minute of each other.

| Call | Items | Not in our DB | Extra vs `prices_for_dates` | Found days covered |
|---|---|---|---|---|
| `prices_for_dates` (limit 1000) | 24 | 6* | — | 10-10…10-15 |
| `grouped_prices` (2–10 nights) | 15 | 2* | 0 | 10-10…10-15 |
| `grouped_prices` (`return_at`, `direct`) | 14 | 1* | 0 | 10-10…10-15 |
| `get_latest_prices` (`show_to_affiliates` false or true: identical) | 24 | 6* | 4, all already in the DB, found 10-09/10 | 10-09…10-15 |
| `month-matrix` | 27 | 9 | 3, found_at **exactly `2026-10-15T00:00:00Z` with an empty `gate`** | 10-10…10-15 |
| `week-matrix` | 3 | 0 | 0 | — |
| `v1/prices/calendar` | 63 | — | ignored the month: departures 2026-10-15 → 2027-05-14, no found date | — |
| `v1/prices/cheap` | 1 | 0 | 0 | — |

\* The items missing from the DB are either outside the 2–10 nights rule (dropped when parsed, kept in
the run archive) or were found after run 57 at 21:00 (two have `search_date` 15-10 and timestamps
after 21:00).

On the sparse route LIS-MLA, `prices_for_dates`, `get_latest_prices` and `grouped_prices` returned the
same 3 / 3 / 1 items.

**Reading:**
- **Same cache:** every endpoint is a view of the same cache. `get_latest_prices` keeps an item a little
  longer after `prices_for_dates` drops it. We already stored all of those, because we have collected
  every 2 h since 10-12.
- **month-matrix:** the 3 points only it returned carry a synthetic midnight timestamp and no agency,
  so no traveller's search can be traced behind them. Under "never fabricate prices" they should not
  enter the database.
- **Limit:** raising `limit` would not help. In the archived runs the largest single response had 46
  items (LIS-LON), so 100 never truncates.

### The real gain: `direct=true` on the call we already make

Three more calls compared `prices_for_dates` for LIS-PAR December with `direct=false` (today) and
`direct=true`.

| | today's call | `direct=true` |
|---|---|---|
| Items / date pairs | 26 / 26 | 26 / 26 (same pairs) |
| Nonstop both ways | 8 | 21 |
| Pairs whose cheapest offer had a stop (nonstop fare hidden) | 17 | 0 (the nonstop fare is 3–45 € dearer: e.g. 98 € with a stop vs 122 € nonstop for 1–12 Dec) |
| New nonstop trips not in the DB | 0 | 13 |
| Found days among nonstop trips | 4 | 7 (10-09…10-15) |

- **LIS-ROM, December, `direct=true`:** 13 nonstop trips, 10 not in the DB. The DB held 6 nonstop rows
  for that month.
- **All `direct=true` items passed** `RouteRules.allows` (transfers 0 and return_transfers 0): 21/21
  and 13/13.
- **Same item shape:** link, `search_date`, airline, flight number, airports. So the observation model,
  `dedup_key`, partner links and the traceability rules are unchanged.

What the database says about the scale:

| On direct-only routes | Rows |
|---|---|
| Rows stored (all) | 3790 |
| Usable (nonstop both ways) | 1625 |
| Discarded for a stop | 2165 (europe 2048, domestic 117) |

90 active routes have observations but none usable. On those, `direct=true` either reveals nonstop
fares or confirms there are none.

Long-haul routes (`max_transfers: 1`) keep `direct=false`.

## 2. `months_ahead` 3 → 6

**Data per departure month (all rows / usable):**

| Departure month | All rows | Usable (nonstop) |
|---|---|---|
| Oct 2026 | 1489 | 491 |
| Nov 2026 | 1390 | 654 |
| Dec 2026 | 1171 | 480 |

**Lead time of usable rows (found → departure), days:**

| Lead time | Usable rows |
|---|---|
| 0–14 | 338 |
| 15–29 | 378 |
| 30–44 | 343 |
| 45–59 | 222 |
| 60–74 | 240 |
| 75+ | 104 |

Activity falls off but doesn't stop.

**Sample calls for months 4–6** (`prices_for_dates`, today's parameters):

| Route | Month | Items |
|---|---|---|
| LIS-BCN | Jan 2027 | 10 |
| LIS-BCN | Feb 2027 | 2 |
| LIS-BCN | Mar 2027 | 2 |
| LIS-NYC | Feb 2027 | 3 |
| OPO-PAR | Mar 2027 | 3 |

For comparison, LIS-BCN in Nov 2026 had 24. The run average today is about 2.1 items per request
(about 2250 per 1080). So months 4–6 might add 25–40 % more rows for 100 % more requests.

**Cost if months 4–6 ran on every run:**
- **Requests:** 2160 a run. Under the 550/min client cap that is about 3.5 min of collection against
  about 1.1 min today (runs now take 64–88 s, median 68 s). Actions wall time would go from about
  2.3 min to about 4.5 min.
- **Actions minutes:** the README budgets 2000 min a month (private repo, GitHub Free). At 12 runs a
  day that is about 1600 min plus full paths: too close.
- **Site size:** negligible. `routes.json` is 235 KB with 276 month rows and 439 calendar days. Low
  prices are capped per origin (`max_low_prices_per_origin`), and months add no pages.

**Value:** the baseline is per departure month and looks back 90 days. Collecting February now means
that when February enters the 3-month window (November), it already has about 30–45 days of history.
Today it would start from 7. `pontes.json` already lists 2027's long weekends, and they would get
data.

**Recommendation:** add months 4–6 on one run a day. Each found day stays in the cache for about 7
days ([Data API][dataapi]), so a daily pass catches nearly every daily low for far months. It only
misses offers replaced within the same day. This needs a small runner change: today `departure_months`
uses one `months_ahead` for every run.

## 3. Reliability rules

### What "mature" means today

The typical low is the median of daily lows. A daily low is the cheapest usable offer that travellers
found that day. It counts only days before the 3-day freshness window (`max_offer_age_days`). The cache
reaches back about 7 days, and we started on 10-12, so **a baseline can have at most 7 days today**
(10-05…10-11).

| Route-months, detector's view now | Count |
|---|---|
| With any usable rows | 276 |
| With ≥ 1 baseline day | 217 |
| ≥ 4 days (mature today) | 30 |
| ≥ 5 days | 15 |
| ≥ 7 days | 4 |

Routes with at least one mature month: 17 at ≥ 4 days, 3 at ≥ 7 days.

The "163 of 515" figure counts all rows, with stops and fresh days, by found date. The detector sees
far fewer.

Daily coverage is thin. A usable route-month has a daily low on a median of 22 % of days (IQR
11–33 %), and only 43 of 276 have one on half the days or more.

### How noisy is a 4-day baseline?

The test set is the 12 route-months with ≥ 9 daily lows (LIS-BCN ×3, LIS-FNC ×3, OPO-PAR ×2, LIS-MAD,
LIS-PAR, LIS-PDL, LIS-ROM).
- **Spread:** the coefficient of variation of daily lows is 0.24 (median; range 0.12–0.37). The highest
  daily low is 2.1× the lowest.
- **Method:** each baseline was recomputed from subsets of n days and compared with the full median.

| n days | median error | 90th-pct error | overstated by > 10 % |
|---|---|---|---|
| 3 | 8–9 % | 24–25 % | 24–26 % |
| 4 | 6–7 % | 20–21 % | 19–20 % |
| 5 | 4 % | 20–21 % | 17–18 % |
| 6 | 4 % | 15–17 % | 11–15 % |
| 7 | 2–4 % | 17–18 % | 9–10 % |
| 8 | 3 % | 11 % | 5–6 % |

These are random and consecutive subsets. With 9–11-day series the larger subsets overlap the full
set, so the errors at 7–8 days are optimistic.

The textbook standard error of a median, 1.25·CV/√n, gives about 15 % at 4 days, 9 % at 10 days and
8 % at 14 days. **At 4 days, one baseline in five is more than 10 % too high. That alone can turn a
real 20 % saving into a "30 %" promotion.**

**Days with one searched date are the outliers.**
- 45 % of the baseline days (160 of 356, in route-months with ≥ 5 days) saw only one departure date.
- On those days the daily low is above 1.25× the month median **24 % of the time**, against 8 % on days
  with two or more dates.
- Examples: the 188 € day in LIS-PAR December and the 191 € day in LIS-ROM October/November.

### The 11 existing deals against what we know now

"Now" means every daily low for the deal's route and month, without the deal's own found day.

| Deal | Route | Status | Price | Baseline at detection (days) | Discount then | Median now (days) | Discount now | Still a promotion? |
|---|---|---|---|---|---|---|---|---|
| 1 | LIS-PAR | expired | 91 | 153.5 (4)† | 41 % | 109 (5) | 17 % | no |
| 2 | OPO-PAR | expired | 60 | 88.5 (4) | 32 % | 87 (10) | 31 % | yes |
| 3 | LIS-PAR | expired | 86 | 153.5 (4)† | 44 % | 109 (5) | 21 % | no |
| 4 | LIS-BCN | rendered | 51 | 76 (6) | 33 % | 69 (10) | 26 % | no |
| 5 | LIS-FNC | rendered | 60 | 102 (5) | 41 % | 99 (9) | 39 % | yes |
| 6 | LIS-BCN | expired | 53 | 76 (6) | 30 % | 69 (10) | 23 % | no |
| 7 | LIS-FNC | rendered | 63 | 102 (5) | 38 % | 99 (9) | 36 % | yes |
| 8 | LIS-FNC | expired | 69 | 102 (5) | 32 % | 99 (9) | 30 % | yes (just) |
| 9 | OPO-FNC | rendered | 54 | 78.5 (4) | 31 % | 64 (7) | 16 % | no (saves 10 €) |
| 10 | LIS-ROM | rendered | 90 | 141 (4) | 36 % | 123 (6) | 27 % | no |
| 11 | LIS-BER | rendered | 89 | 134 (4) | 34 % | 111.5 (6) | 20 % | no |

† Detected before `direct_only` applied to the baseline. Rebuilt with nonstop fares only, it had 2
days at 107.5 €. That deal later expired as "não é ida e volta com voos diretos".

- **Bias:** every discount fell once more days were known. The median drop was 7 points over the 9
  deals not affected by the rule change (#1 and #3 are left out).
- **Why:** this is the expected selection effect. A deal fires when a small-sample baseline happens to
  be high, and the larger sample then pulls it back.
- **Caveat:** later days can include a real fare drop (a sale). In that case the "deal" price is the
  new normal, which is exactly the kind of deal Miguel wants to avoid posting.

**Under `min_baseline_days: 7`:**
- **Existing deals:** none of the 11 would have been created; the most any had was 6 days.
- **Replay of the detector over runs 19–57:**

| Rule | Candidates | Hold ≥ 30 % against today's median | ≥ 20 % |
|---|---|---|---|
| Today's rule | 8 | 3 | 7 |
| Min 7 days | 0 | — | — |
| Min 5 days and span ≥ 4 | 5 | 3 | 5 |
| Threshold 0.35 | 3 | 2 | 3 |
| Price below every baseline day | 3 | 0 | 2 |

The replay reproduces deals #4–#11. "Price below every baseline day" filters the wrong ones on small
samples.

### Proposed rules

| | Low prices (site, automatic) | Promotion candidates (reviewed, posted) |
|---|---|---|
| Daily lows needed | **≥ 7** (today 4) | **≥ 10** (today 4) |
| What counts as a day | a day with **≥ 2 distinct departure dates** among usable rows | same |
| Span of those days (first → last found date) | ≥ 6 days | **≥ 9 days** (covers a weekday/weekend cycle) |
| Threshold | 0.15 (unchanged) | 0.30 and ≥ 15 € (unchanged) |
| Estimator | median (unchanged) | median (unchanged) |
| Shown to the reviewer | — | days, span, min–max of daily lows (item 3) |

**Why these numbers:**
- **10 days:** brings the 90th-percentile baseline error to about 10 %, under half the 30 % threshold.
- **The ≥ 2-dates rule:** drops the days that are three times as likely to be high outliers.
- **No extra "minimum observations" rule:** two dates per day already gives at least 2 rows per day,
  so at least 20 per promotion baseline.
- **No extra outlier trimming:** the median already resists one bad day, and the ≥ 2-dates rule
  removes the main source of bad days.

**Effect today:**
- **Route-months:** 0 qualify for promotions and 7 have ≥ 5 qualifying days.
- **Low prices:** 32 on 10 routes under today's rule, 5 on 2 routes at ≥ 7 days.
- **With `direct=true`:** the first run backfills about 7 found days per busy route-month (seen on
  LIS-PAR/LIS-ROM December). Busy routes should then reach 10 days with a 9-day span by about
  20–25 October.

`detector.py` stays pure. The new rules are `DetectorConfig` fields, for example
`min_baseline_days_promo`, `min_baseline_span_days` and `min_dates_per_day`, and `Baseline` gains the
span it already has, plus a count of qualifying days.

## 4. Collection cadence

**New data per run, by gap since the previous run** (runs 19–57; "usable" = nonstop, within the
rules):

| Gap | Runs | New rows/run (median) | New usable/run | Daily lows changed/run | Usable per hour |
|---|---|---|---|---|---|
| ≤ 0.5 h | 12 | 6 | 2 | 1 | 19 |
| 0.5–1.5 h | 10 | 25 | 9 | 4.5 | 16 |
| 1.5–2.5 h | 14 | 50 | 23 | 12.5 | 13 |
| 2.5–6 h (overnight) | 3 | 37 | 13 | 12 | 4 |

- **Short gaps still find something:** even runs 3–15 min apart found new rows (run 53: 54 new), so
  the cache changes continuously. Because it keeps one offer per date pair, a fare replaced between
  two runs is lost.
- **Nights are quiet:** the `found_at` times in the samples cluster at 05–22 UTC.
- **For baselines,** a daily low stays in the cache for about 7 days, so cadence matters little.
- **For promotions,** cadence matters for speed and for the recheck before posting
  (`posting.max_check_age_hours: 6`).

**What actually happens:**

| Source | Schedule | Observed |
|---|---|---|
| GitHub Actions | cron `17 */2 * * *` | 9 scheduled runs on 10-14/15 came 4.4–6.8 h apart (median 5.5 h); each took 1.7–6.2 min of wall time |
| PC (Windows Task Scheduler) | every 2 h | the on-the-hour runs in `fetch_runs` (09:00, 11:00, … 21:00) |

GitHub's cron is best effort. The README plans to unregister the PC task after a clean week; at that
point the real cadence drops to about 5 h.

**Recommendation:**
- **Keep 2 h.** Hourly doubles requests and Actions minutes for about 1.2× the usable rows per hour,
  and would need roughly 2200+ Actions minutes a month.
- **Make the 2 h reliable before removing the PC task,** e.g. with an external cron calling
  `workflow_dispatch` / `repository_dispatch` (the workflow already accepts both).
- **Optional:** skip 01:00–06:00 Lisbon and spend those minutes on the daily months 4–6 pass.

## Method and caveats

- **History is short:** only 11 found days (10-05…10-15). "Typical low now" is itself based on 5–10
  days, so the hindsight check is a lower bound on the noise, not ground truth. Rerun this analysis
  (scripts were in the session scratchpad) once there are 30+ days.
- **Few samples:** the `direct=true` gain rests on 2 route-months (LIS-PAR December, LIS-ROM December).
  The DB-wide share of rows dropped for stops (57 %) supports it. The first run with the change will
  give the real number.
- **Shared rate limit:** the token's limit is shared. One sample call saw `x-rate-limit-remaining: 582`
  of 600 because a pipeline run was collecting at the same time.
- **Replay approximation:** it took "offers present at run r" to be rows with
  `run_id ≤ r ≤ last_run_id`, because rows are deduplicated.

## Sources

- [Aviasales Data API][dataapi], Travelpayouts support, article 203956163 (updated 2026-09-06):
  endpoints, parameters, the 7-day cache, markets, the "recommended to use instead" notes.
- [API rate limits][limits], article 4402565416594 (limits per minute from 2024-06-14, 429 behaviour,
  `X-Rate-Limit*` headers).
- [What are the restrictions on API requests?][restrict], article 205895848 (cache results for 24 h).
- [Aviasales GraphQL][graphql], article 4417975783314.
- [Travelpayouts API reference (slate)][slate]: v1/v2 methods (`month-matrix`, `week-matrix`,
  `calendar`, `cheap`, `latest` "last 48 hours").
- Repo: `src/escapadinha/collector/travelpayouts.py`, `detector.py`, `recheck.py`, `site_data.py`,
  `config.yaml`, DECISIONS D10, D13, D23, D24, D25, D26, README "Minutes used" / "PC fallback",
  `.github/workflows/pipeline.yml`.
- Data: `data/escapadinha.db` (runs 1–57, 4050 observations, 11 deals), archives
  `data/objects/archive/runs/0000001–16`, `gh run list --workflow pipeline.yml`, 20 API calls on
  2026-10-15 ~21:25 UTC.

[dataapi]: https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
[limits]: https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits
[restrict]: https://support.travelpayouts.com/hc/en-us/articles/205895848-What-are-the-restrictions-on-API-requests
[graphql]: https://support.travelpayouts.com/hc/en-us/articles/4417975783314-Aviasales-GraphQL-for-access-to-Flights-Data-API
[slate]: https://travelpayouts.github.io/slate/

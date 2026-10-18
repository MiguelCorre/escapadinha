# Detector backtest: confidence, new low and lead time measured on the stored history

*Issue #47 (M1), 2026-10-18. Read-only: a copy of `data/escapadinha.db` pulled from R2 at
generation 58 (runs 1–74, last collection 2026-10-18 11:46 UTC, 6 765 observations found
2026-10-05 … 10-18, 360 active routes), opened `mode=ro` and copied into memory by
`scripts/backtest_detector.py`. No API call, no store change. Every figure below is the script's
output; rerun it to refresh them.*

**Builds on** [`2026-10-15-data-reliability.md`](2026-10-15-data-reliability.md) (§3: the maturity
gate, D40) and [`2026-10-15-more-data-and-site-ideas.md`](2026-10-15-more-data-and-site-ideas.md)
(§1: CV 0,20 and the lead-time effect; §3 points 1, 2, 3 and 7; draft T2). The two reports
replayed the detector by hand; this one makes the replay a script in the repository
(`src/escapadinha/backtest.py`), so every later change to the detector's thresholds can be measured
the same way.

## Summary

1. **The maturity gate (D40) is what binds today, and it will for a few more days.** Over the
   last 14 days no route-month was mature for promotions (10 counted days spanning 9), so D40 and
   every D44 variant on top of it gave **0 candidates** and the same **6 distinct low prices**
   (10 route-months are mature for low prices, the longest with 9 counted days). The D44 rules
   therefore had to be measured on the permissive pre-D40 gate (4 days, every day counts), where
   there were 27 candidates to judge.
2. **The new-low rule is the one that pays.** On the permissive gate it keeps 16 of 27
   candidates and raises the share that is still a promotion today (≥ 30 % and ≥ 15 € below the
   route-month's typical low from everything stored, the candidate's own day left out) from
   **56 % to 75 %**. Of the 11 it drops, 8 are not a promotion today; of the 15 that are, it keeps
   12. Every domestic candidate but one goes (0 of 6 hold today).
3. **The lead-time filter has no measurable gain yet.** It changes the typical low of 12 of 199
   route-months (median −4 %, but in both directions: 7 down, 5 up), costs 10 % of the low prices
   (109 → 98 distinct) and one route-month's low-price maturity, and leaves the hindsight hold rate
   where it was (54 % vs 56 %). Thirteen days of history are too few to see the 14 % last-week
   premium the earlier report measured. The rule is shipped as a setting with the ticket's
   default (7 days); turning it off is a one-line config change, and this is the one threshold
   where Miguel's call goes against thin evidence either way.
4. **Confidence as words.** With 7–9 counted days every mature month is `medium`; the CV of
   their daily lows has median 0,20 (p10 0,14, p90 0,29) and 7 of 10 are at or under 0,25, so
   the proposed `high` (≥ 14 days, CV ≤ 0,25) would admit most of them once they reach 14 days,
   around 2026-10-23 for the busiest routes. Requiring `high` for low prices today would empty
   the route pages (0 low prices).
5. **The data-reliability replay table is reproduced exactly** (8 / 0 / 5 / 3 / 3 candidates for
   its five rule sets over runs 19–57, the 8 being deals #4–#11), so the script measures what the
   earlier hand replay measured.

## 1. What the script does

`uv run python scripts/backtest_detector.py data/escapadinha.db --preset d44 --days 14 --candidates --state`

- **Runs:** every completed collection run (`fetch_runs.scope = 'full'`) on the chosen days (by
  default the 14 Lisbon days before the latest run's day; `--runs 19-57` picks ids). The detector's
  `now` is each run's start time.
- **What a run saw:** offers are stored once (D18), so "present at run r" is approximated by
  `run_id ≤ r ≤ last_run_id` and "known at run r" by `run_id ≤ r`, as in data-reliability §3. A
  fare that left the cache and came back counts as present in between.
- **Judges:** `detector.detect` with one `DetectorConfig` per rule set (routes and their rules
  from the copy's `routes` table), remembering per rule set which observations became deals and
  which trips were flagged in the last `dedupe_days`, like the pipeline. Then, per candidate:
  - **expired ≤ 24 h:** `recheck.recheck` (the pipeline's own) at every run within the next 24 h
    against that run's offers; a candidate with no later run inside 24 h is "not judged";
  - **holds today:** against its route-month's typical low from everything stored by the latest
    run under the same rule set, without the candidate's own found day (the research's check);
  - **new low:** whether the price beat every eligible offer of the baseline window by
    `new_low_margin` (reported for every set, enforced only where `require_new_low` is on);
  - **confidence** of the typical low it was judged against.
- **Low prices:** the mean per run and the distinct observations over the window.
- `--state` lists every route-month's typical low at the latest run under the configured
  detector, with and without the lead-time filter.

## 2. The data-reliability table, reproduced (runs 19–57, 13–15 October)

| Rule set | Candidates (routes) | Expired ≤ 24 h | Holds today | New lows | Low prices / run | Distinct low prices |
|---|---|---|---|---|---|---|
| before (D3/D24: 4 days, every day counts) | 8 (5) | 0/8 | 3/8 (38 %) | 3/8 (38 %) | 14,4 | 38 |
| min 7 days, every day counts | 0 | – | – | – | 1,3 | 5 |
| min 5 days, span ≥ 4 | 5 (2) | 0/5 | 0/5 | 0/5 | 8,5 | 19 |
| threshold 0,35 | 3 (2) | 0/3 | 1/3 | 1/3 | 14,4 | 38 |
| below every baseline day (new low, margin 0) | 3 (3) | 0/3 | 3/3 (100 %) | 3/3 | 14,4 | 38 |

The research's own table (candidates 8 / 0 / 5 / 3 / 3; "hold ≥ 30 % against today's median"
3 / – / 3 / 2 / 0) is reproduced in the candidate counts. The hindsight column differs because
"today" moved: the research judged against the median of 2026-10-15, this run against
2026-10-18's, three more days of daily lows. The three that hold now are the three new lows
(OPO-FNC 54 €, LIS-ROM 90 €, LIS-BER 89 €); the five that don't are the LIS-BCN and LIS-FNC
deals detected on 14 October on 5–6-day baselines with CV 0,27–0,28.

## 3. The last 14 days (runs 1–71, 12–17 October, 68 runs on 6 days)

Promotion candidates per rule set. "Confidence" is the level of the typical low each candidate
was judged against; the pre-D40 sets call 4 days mature, so their candidates read `medium`.

| Rule set | Candidates (routes) | Per day | Expired ≤ 24 h | Holds today | New lows | Low prices / run | Distinct low prices |
|---|---|---|---|---|---|---|---|
| before (D3/D24) | 27 (13) | 4,5 | 2/27 (7 %) | 15/27 (56 %) | 16/27 (59 %) | 15,6 | 109 |
| before + new low (≤ 0,95 × cheapest seen) | 16 (8) | 2,7 | 1/16 (6 %) | **12/16 (75 %)** | 16/16 | 15,6 | 109 |
| before + lead time (baseline from offers ≥ 7 days ahead) | 26 (12) | 4,3 | 3/26 (12 %) | 14/26 (54 %) | 15/26 (58 %) | 14,6 | 98 |
| before + new low + lead time | 15 (7) | 2,5 | 2/15 (13 %) | 11/15 (73 %) | 15/15 | 14,6 | 98 |
| D40 (2 dates a day, 7 / 10 spanning 9) | 0 | – | – | – | – | 0,3 | 6 |
| D40 + new low | 0 | – | – | – | – | 0,3 | 6 |
| D40 + lead time | 0 | – | – | – | – | 0,3 | 6 |
| D40 + threshold 0,35 | 0 | – | – | – | – | 0,3 | 6 |
| **D44 as configured** (D40 + new low + lead time) | 0 | – | – | – | – | 0,3 | 6 |
| D44, `low_confidence: high` | 0 | – | – | – | – | 0,0 | 0 |

By route kind (the sets with candidates):

| Rule set | Kind | Candidates | Expired ≤ 24 h | Holds today | New lows | Distinct low prices |
|---|---|---|---|---|---|---|
| before | domestic | 6 | 0/6 | **0/6** | 1/6 | 32 |
| before | europe | 21 | 2/21 | 15/21 (71 %) | 15/21 | 76 |
| before | long_haul | 0 | – | – | – | 1 |
| before + new low | domestic | 1 | 0/1 | 0/1 | 1/1 | 32 |
| before + new low | europe | 15 | 1/15 | 12/15 (80 %) | 15/15 | 76 |
| before + lead time | domestic | 6 | 0/6 | 0/6 | 1/6 | 30 |
| before + lead time | europe | 20 | 3/20 | 14/20 (70 %) | 14/20 | 67 |

### 3.1 What the new-low rule drops and keeps

The 11 candidates the rule drops (not 5 % below the cheapest offer seen for the route-month):

| Route | Price | Discount then | Discount today | Promotion today? | Baseline days, CV |
|---|---|---|---|---|---|
| LIS-BCN | 51 € | 33 % | 24 % | no | 6, 0,27 |
| LIS-BCN | 53 € | 30 % | 21 % | no | 6, 0,27 |
| LIS-FNC | 60 € | 41 % | 30 % | no (saves less than 15 € against 86 €? no: 30 % exactly, below the threshold by rounding) | 5, 0,28 |
| LIS-FNC | 63 € | 38 % | 26 % | no | 5, 0,28 |
| LIS-FNC | 69 € | 32 % | 18 % | no | 5, 0,28 |
| LIS-MIL | 47 € | 52 % | 31 % | **yes** | 4, 0,60 |
| LIS-MIL | 57 € | 42 % | 16 % | no | 4, 0,60 |
| OPO-FNC | 94 € | 31 % | 13 % | no | 4, 0,61 |
| OPO-LUX | 97 € | 37 % | 37 % | **yes** | 4, 0,23 |
| OPO-LUX | 98 € | 37 % | 36 % | **yes** | 4, 0,23 |
| FNC-LIS | 54 € | 31 % | 13 % | no | 4, 0,36 |

The 16 it keeps: 12 hold today (OPO-PAR 60 €, OPO-LON 60/58/62/65 €, OPO-MIL 47/48/50/51 €,
LIS-VCE 243 €, LIS-WAW 127/137 €), 4 don't (OPO-FNC 54 €, LIS-ROM 90 €, LIS-BER 89 €, OPO-MIL
55 €, all between 21 % and 29 % below today's typical low). Across all 27 the median discount
fell from 37 % at detection to 32 % today (median 2,6 points per candidate, less than the
7 points data-reliability saw: the baselines are a week older now).

Reading: a −30 % day that is not a new low is, three times out of four, a cheap day of a noisy
month (CV 0,27–0,61) rather than a promotion. The two OPO-LUX candidates the rule loses are real
(37 % today) and were not new lows because a 93 € fare had been seen; with a 0 % margin they
would pass, with 5 % they don't. The margin is the trade between those two and the LIS-MIL /
LIS-FNC false positives.

### 3.2 Expired within 24 h

Rare in this window: 2 of 27 under the permissive gate (OPO-PAR 60 € on 12 October, "o preço
subiu para 70 €", the real case D13 records; OPO-LUX 97 € on 17 October, "subiu para 110 €"),
3 of 26 with the lead-time filter (the same two plus one more OPO-LUX). The 24-hour expiry is a
bookability proxy; with 2-hourly runs it says the cache kept the fare for a day. It does not
separate the rule sets yet.

## 4. Where the data stands (latest run, 2026-10-18 11:46 UTC)

601 route-months have usable offers; 199 have at least one counted day.

| Counted days | Without the lead filter | With lead ≥ 7 days |
|---|---|---|
| ≥ 1 | 206 | 199 |
| ≥ 4 | 33 | 30 |
| ≥ 7 (low prices) | 11 | 10 |
| ≥ 10 (promotions) | 0 | 0 |
| ≥ 14 (high confidence) | 0 | 0 |

The 10 route-months mature for low prices, all `medium` confidence:

| Route | Month | Days (without filter) | Typical low (without filter) | CV | Median lead (days) |
|---|---|---|---|---|---|
| LIS-BCN | 2026-11 | 9 | 62 € | 0,23 | 36 |
| LIS-FNC | 2026-11 | 9 | 55 € | 0,14 | 35 |
| LIS-BCN | 2026-10 | 8 (9) | 121 € (128 €) | 0,29 | 13 |
| LIS-FNC | 2026-10 | 8 | 68 € | 0,29 | 19 |
| LIS-FNC | 2026-12 | 8 | 59 € | 0,27 | 64 |
| LIS-PAR | 2026-11 | 8 | 96 € | 0,15 | 37 |
| LIS-ROM | 2026-11 | 8 | 78 € | 0,17 | 40 |
| LIS-MAD | 2026-10 | 7 | 77 € | 0,18 | 14 |
| LIS-PAR | 2026-12 | 7 | 109 € | 0,21 | 63 |
| OPO-PAR | 2026-11 | 7 | 79 € | 0,14 | 44 |

CV of their daily lows: median 0,20, p10 0,14, p90 0,29; 7 of 10 at or under 0,25 (the
more-data report measured 0,20 / 0,11 / 0,34 on the 30 route-months the old gate called mature).
The maximum counted days anywhere is 9: the first promotion-mature months need one more day,
with the span already satisfied, so the 20–25 October estimate of D40 holds.

**The lead-time filter** changes the typical low of 12 route-months, all October (the only
month where found days are within a week of departure):

| Route | Month | With filter | Without |
|---|---|---|---|
| LIS-BCN | 2026-10 | 121 € | 128 € |
| OPO-PAR | 2026-10 | 140 € | 154 € |
| LIS-FRA | 2026-10 | 374 € | 400,50 € |
| LIS-VCE | 2026-10 | 314 € | 361,50 € |
| LIS-SVQ | 2026-10 | 46 € | 66 € |
| OPO-MAD | 2026-10 | 63 € | 83,50 € |
| LIS-MIL | 2026-10 | 158 € | 162,50 € |
| LIS-NYC | 2026-10 | 601,50 € | 609 € |
| LIS-ATH | 2026-10 | 238 € | 239 € |
| OPO-BCN | 2026-10 | 74,50 € | 73 € |
| OPO-FNC | 2026-10 | 93 € | 84,50 € |
| LIS-ALC | 2026-10 | 333 € | 191 € |

Nine fall (the expected direction: last-week fares were the dear ones), three rise (the
last-minute fares were the cheap ones, e.g. LIS-ALC). It takes OPO-PAR October below the
low-price maturity (7 → 6 counted days). On a month about to depart the filter removes exactly
the days that were being collected, so on short histories it costs more days than it corrects.

## 5. Proposed values (Miguel decides)

| Setting | Proposed | Why | What else was considered |
|---|---|---|---|
| `require_new_low` | **true** | 56 % → 75 % hindsight precision on the only gate with candidates; drops every noisy-month false positive but one | off: 27 candidates, 12 of them not promotions today |
| `new_low_margin` | **0,05** | the ticket's value; keeps the rule from passing on a 1 € difference | 0: also keeps OPO-LUX 97/98 € (real) and LIS-MIL 47 € (real), but the test set is 27 candidates; revisit at 30 days |
| `baseline_min_lead_days` | **7** (the ticket's) with a flag | the research's 1,14× last-week ratio; here: no gain yet, −10 % low prices, mixed shifts on 12 October months | **0 until the 30-day rerun** is the honest alternative; a one-line config change |
| `confidence.high_days` / `high_max_cv` | **14 / 0,25** | 7 of 10 mature months have CV ≤ 0,25; 14 days is where the median's standard error (1,25·CV/√n) drops to about 8 % | 20 / 0,20: nothing would be `high` before November |
| `low_confidence` | **medium** | `high` empties the route pages today (0 low prices) | `high` once months reach 14 days, if the low-price rows look noisy |
| `threshold`, `min_saving_eur` | unchanged 0,30 / 15 | 0,35 removed 5 of 8 in the research's replay and 0 of 0 under D40 | – |

What posts say follows from the confidence (D44): "−x % face ao habitual" only at `medium` or
`high`; at `low` (a price-cap deal, or a config that lets a 4-day month through) a new low says
"o preço mais baixo que vimos nesta rota", and nothing else makes a claim.

## 6. Caveats

- **Thirteen days of history**, six of them in the replay window, 27 candidates in the only set
  with any. The rates above have wide intervals; the 75 % is 12 of 16.
- **Hindsight is itself young:** "today's" typical lows rest on 7–9 days. The research's warning
  stands: a later fare drop makes a real deal look like the new normal.
- **The presence approximation** (D40's): a fare that left the cache and returned counts as
  present in between, so "expired ≤ 24 h" is a lower bound. The archives would settle it.
- **No promotion-mature month yet**, so D44's rules were measured on a gate the pipeline no longer
  uses. The first weeks after 20–25 October are the real test: rerun with `--days 14` then, and
  again at 30 days (`--state` shows when the first `high` months appear).

## Rerun

```bash
uv run escapadinha store pull
uv run python scripts/backtest_detector.py data/escapadinha.db --preset data-reliability --runs 19-57
uv run python scripts/backtest_detector.py data/escapadinha.db --preset d44 --days 14 --candidates --state --json backtest.json
```

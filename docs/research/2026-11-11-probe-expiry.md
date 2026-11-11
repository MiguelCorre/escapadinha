# Should the probe expire a cache deal? (2026-11-11)

*A read-only measurement on the bucket's backup of 2026-11-11 (last collection run 2026-11-10
23:47 UTC), opened read-only and copied into memory (`backtest.open_copy`). No API call, no
change to the bucket or to `data/escapadinha.db`. Every number below is the output of
`scripts/backtest_detector.py --preset probe` (D44's backtest script); rerun it to update them.*

## Question

A deal whose own source is the Travelpayouts cache is rechecked only at the cache (D47: a deal
is rechecked at its own source). The cache can keep returning a price that is no longer
bookable, so a promotion can stay on the site, "checked", for days, until the stale-price timer
(found more than three days ago) expires it. The PC probe (D48, D49: `google_flights`, `kayak`,
comparison sources) searches the same trips, and it often sees a higher price. The candidate
rule: **expire a cache deal when a probe engine saw the same trip recently at a clearly higher
price.** Does the data support it, and with which thresholds?

## Data

- 31 deals from the cache since 2026-10-12. **17 are "compared"**: the probe searched their trip
  while they were open (every cache deal open after the probe started on 2026-10-24 21:00;
  the 14 before had expired). 6 of the 17 were approved (all by the rules, D46).
- 4 927 probe observations (Google Flights 2 925 since 24/10, Kayak 2 002 since 26/10), 466
  import runs. No probe searches on 01/11 and few on 29–30/10 (PC or probe off); Kayak had
  low days (29/10, 03/11, 08/11).
- **Control set:** the 214 Ryanair-source deals (D47) that the probe searched while they were
  open. Their price is rechecked at the seller itself every run, so while one is open its price
  is real (give or take the half hour between runs).

## Method

Code: `src/escapadinha/backtest.py`, section "the probe against the cache's deals"
(`cache_deals` loads; `truth_at`, `fires`, `first_fire`, `probe_grid`, `probe_report` are pure),
tests in `tests/test_backtest_probe.py`.

- **Match.** The trip as `pipeline.also_seen` matches it: the same origin, destination city,
  departure date and return date (`db.trip_observations_by_source`'s WHERE). All the rows are
  used, not only the newest per source. A stored row is one search, or two when the same price
  was seen again on the same day (first and last sighting). Per search, the engine's cheapest
  option counts (the probe reads the cheapest nonstop itinerary, then its sellers). A search is
  usable from the start of the run that imported it (import lag 0.1–0.7 h here).
- **A rule** (`ProbeRule`): at each recheck from detection to the deal's real expiry, take each
  engine's newest usable search no older than the max age. The rule fires when it is at least
  `pct` **and** `€` above the deal's price, on any engine, on both engines, or on Google Flights
  alone. Two guards that are not in `also_seen`: `newer_than_price` (only searches made after the
  deal's price was found; on by default) and `same_airport` (only searches that landed at the
  deal's arrival airport). The rule is judged at its first firing. *Amended the same day, after
  review (D65):* "when the price was found" is the observation's exact `found_at` when known,
  else **the first time the pipeline fetched it** (never earlier than the real find), no longer
  the start of its found day: a deal detected in a run has no `found_at` until the enrichment,
  which runs after detection. The shipped rule also judges nonstop deals only (the probe reads
  only nonstop itineraries) and takes each search's cheapest option at the deal's airport. On
  this copy the rerun changes no figure below: every fire, false positive, control count and
  hour is the same; one probe reading's truth (deal 71, Google Flights 26/10 00:15, not a fire)
  moved from unknown to real (cache), because the cache's re-found rows now count from their
  first fetch too. All 17 compared deals are nonstop.
- **Truth** (`truth_at`), the best evidence at the moment of the search that fired, in order:
  1. **airline** (strong): Ryanair's own fare (D47) for the same carrier, airport and dates,
     whose sightings cover the moment (else seen within 3 h of it). Real if it is within the
     recheck's 5 % tolerance of the deal's price (D53), else stale. Only Ryanair-operated deals
     can have this truth.
  2. **cache** (medium): the cache re-found the same itinerary (carrier, airport) at the deal's
     price, within 5 %, in the 24 h after the moment: real.
  3. **rose** (weak): the recheck expired the deal `gone` within 24 h after the moment, the
     cache's price having risen: stale.
  4. **timer** (weakest): the same, by the stale-price timer: stale only in the sense that
     nobody re-found the price for three days.
  5. otherwise **unknown**.
- **False positive** = a fire whose truth is real. On the control set, a fire more than 1 h
  before the deal's own expiry is a false positive.
- **Grid**: margin 5/10/15/20/25 % × 0/5/10/15 € × max age 6/12/24/48 h × engines
  any/both/google_flights × trip/airport match, with the found-time guard (480 rules), plus the
  same at 12 and 24 h without the guard (120 rules).

## Results

### The compared deals

| Deal | Route, airport | Trip | Price | Carrier, seller | Approved | Expiry | Probe searches GF/K | Gap to the probe (first; min … max) | Ryanair's own price |
|---|---|---|---|---|---|---|---|---|---|
| 14 | OPO-FNC FNC | 06–12/12 | 54 € | FR, Kiwi.com | no | gone (timer) 25/10 | 1/0 | −9 % | – |
| 16 | OPO-FNC FNC | 17–21/12 | 48 € | FR, Clickavia | no | gone (timer) 27/10 | 3/1 | −8 % … −4 % | – |
| 17 | OPO-FNC FNC | 12–16/12 | 49 € | U2, Clickavia | no | gone (timer) 27/10 | 3/2 | −12 % … −2 % | – |
| 18 | OPO-PAR BVA | 08–10/12 | 65 € | FR, Kiwi.com | no | gone (timer) 28/10 | 7/3 | −8 % … +0 % | 59.98–64.98 |
| 19 | OPO-FNC FNC | 12–14/12 | 50 € | FR, Clickavia | no | superseded 27/10 | 3/2 | −12 % … −6 % | – |
| 71 | OPO-FNC FNC | 30/11–03/12 | 50 € | FR, Tickets | no | superseded 26/10 | 2/0 | −4 % | 47.16 |
| 163 | OPO-PAR BVA | 03–06/12 | 67 € | FR, Kiwi.com | no | superseded 28/10 | 6/3 | +4 %; +3 % … +30 % | 68.87 → 81.02 |
| 175 | OPO-FNC FNC | 30/11–03/12 | 48 € | U2, Farera | no | gone (rose) 26/10 | 2/2 | −4 % … +0 % | – |
| 227 | OPO-BCN BCN | 05–07/12 | 40 € | FR, Clickavia | no | superseded 28/10 | 3/2 | +0 % … +2 % | 39.98–40.98 |
| 283 | OPO-MIL BGY | 11–14/12 | 42 € | FR, Tickets | rules | gone (timer) 30/10 | 5/4 | +7 %; +7 % … +19 % | 46.98 → 50.98 |
| 342 | OPO-FNC FNC | 15–23/12 | 44 € | U2, Clickavia | no | superseded 28/10 | 1/0 | −2 % | – |
| 375 | OPO-FNC FNC | 30/11–03/12 | 48 € | U2, Farera | no | superseded 28/10 | 1/0 | +6 % | – |
| 408 | OPO-PAR BVA | 20–23/11 | 49 € | FR, Kiwi.com | rules | gone (timer) 03/11 | 5/5 | +6 %; −2 % … +61 % | 51.98 → 78.98 |
| 412 | OPO-MIL MXP | 12–15/02 | 58 € | W4, Farera | rules | gone (timer) 05/11 | 6/4 | +38 %; +24 % … +38 % | – |
| 414 | OPO-MIL MXP | 12–14/02 | 51 € | W4, Kiwi.com | rules | gone (rose) 10/11 | 5/5 | +4 %; +2 % … +8 % | – |
| 415 | LIS-MIL MXP | 12–14/02 | 46 € | U2, Farera | rules | open | 1/2 | +4 %; +4 % … +30 % | – |
| 417 | LIS-MIL LIN | 18–22/02 | 42 € | U2, Farera | rules | open | 1/1 | +50 % | – |

Expiry times before 03/11 are the v19 backfill's (approximate, D56). Every compared deal is
nonstop both ways and cabin-bag only (`with_baggage = 0`), so the probe's nonstop search and
its basic fares compare like with like: **nonstop and baggage are not a source of the gap.**

- **What happened afterwards.** 163: Ryanair went from 68.87 € to 78.76 € on 27/10 02:19, and the
  cache kept 67 € until the re-evaluation superseded the deal 22 h later. 408 (approved): Ryanair
  went from 48.98 € to 80.98 € on 30/10 22:49, and the cache kept 49 € until the timer on 03/11
  00:19. The site showed a price that was 60 % too low for 73 h. 283 (approved): Ryanair was at
  46.98 € (+12 %) from 27/10 12:49, and the cache kept 42 € until the timer on 30/10 00:19.
  412 and 417 have no airline source (Wizz Air, easyJet). The cache never re-found 412's 58 €
  (timer), and 417 is still open. 414 is the counter-example: the cache re-found 52–53 € at
  Kiwi.com every day while Google Flights showed 55 € (+8 %).

### The two engines agree

There are 25 pairs (a Google Flights and a Kayak search of the same trip within 1 h, during a
deal's life). The two engines are a median 2.2 % apart (max 20 %, 415: 60 € vs 50 €), and 20 of
the 25 pairs are within 5 %. Kayak was the lower of the two in 19 pairs, Google Flights in 3. Both engines were ≥ 10 % above the deal in 11 pairs, both ≥ 5 % above
in 14, both within ±5 % in 7, either one below the deal in 7. "One engine ≥ 10 % above, the
other within 5 %": 0 pairs.

### Control: when the deal's price is live, the probe agrees

There are 628 probe searches of the 214 Ryanair deals during their lives, at their own airport.
The median gap is −1.4 %. 3 searches are ≥ 5 % above the deal, **0 are ≥ 10 % above**, and 363
are below it. So a probe price 10 % above the deal is a signal that does not occur by chance
against a live price.

### The rule grid (outcome classes)

The full grid is in the script's output. Rows with the same outcome are grouped here.
"Unknown" means no truth. "Early" is the median of hours before the real expiry, for the
deals that later expired.

| Rules (found-time guard on unless said) | Fires | Stale (airline) | Real: false positives | Unknown | Approved when fired | Early h | Control false positives |
|---|---|---|---|---|---|---|---|
| any or Google Flights, ≥ 5 %, 0 € (any age) | 8 | 163, 408 | **375, 414** | 283, 412, 415, 417 | 5 | 64 | any: **262, 409**; GF: none |
| any or Google Flights, ≥ 5–10 %, ≥ 5 € or ≥ 10 %, 0 € | 6 | 163, 408 | – | 283, 412, 415, 417 | 5 | 53 | – |
| any or Google Flights, ≥ 15 %, ≤ 5 € | 6 | 163, 283, 408 | – | 412, 415, 417 | 5 | 38 | – |
| **both, ≥ 5–15 %, with ≥ 5 € (or ≥ 10 %, 0 €), any age** | **5** | **163, 283, 408** | **–** | **412, 417** | **4** | **38** | **–** |
| both, ≥ 5 %, 0 €, ≤ 24 h | 6 | 163, 408 | – | 283, 412, 415, 417 | 4 | 56 | – |
| both, ≥ 10 € or ≥ 20 % | 3–4 | 408 (+163 at 10 €) | – | 412, 417 | 3 | 54–56 | – |
| without the found-time guard, ≥ 5 %, 0 € | 8 | 163, 408 | 375, 414 | 283, 412, 415, 417 | 5 | 64 | 17–26 Ryanair deals |
| without the guard, ≥ 10 %, ≥ 5 €, both | 5 | 163, 283, 408 | – | 412, 417 | 4 | 38 | 312 |

- **The € floor removes the two known false positives.** 375 (Google Flights 51 € vs 48 €,
  +3 €) and 414 (55 € vs 51 €, +4 €) were real (the cache re-found them). Every rule with a 5 €
  floor, or a 10 % margin, leaves them out.
- **The found-time guard matters.** Without it, the rules fire at detection on Ryanair deals
  that the probe searched hours before the price dropped (the drop is what made them deals):
  up to 26 control false positives at 5 %, and deal 312 even with both engines at 10 % and 5 €.
  With it, there are none at any threshold at or above 5 € or 10 %.
- **The max age hardly matters.** The import lag is under an hour and the guard removes the old
  searches. 6, 12, 24 and 48 h give the same fires for the recommended rule. 48 h only
  lets in 415's two-day-old Bergamo searches on an "any" rule.
- **"Both engines" is what leaves 415 out.** There Google Flights saw 60 € (+30 %) and Kayak
  50 € (+9 %), 48 € earlier. The deal's 46 € may well be real at Farera. Requiring both engines
  costs nothing on the known cases.
- **Airport match.** The only difference from the city match is 415's Bergamo searches (another
  airport, searched for the routes' rotation). The recommended rule fires on the same deals
  either way. Match the airport anyway, because the probe searches airports.

### The truth is weak

- Strong truth (Ryanair) exists for only 6 of the 17 compared deals. It confirms the three
  stale fires (163, 283, 408) and three real non-fires (18, 71, 227: the probe and Ryanair
  within 5 %, or the probe lower).
- The two unknown fires, 412 and 417, are on Wizz Air and easyJet, for which there is no
  airline source (Wizz Air is behind a WAF challenge, D47). The evidence for them is
  circumstantial only: both engines agreed (+24–38 %, +50 %), Google Flights listed the airline
  itself as a seller at the higher price (417: easyJet 63 €), and the cache never re-found 412's
  price.
- The "stale known" list of the grid (9 deals) includes timer truths that the probe
  contradicts: 14, 16, 17 and 175 expired by the timer or a rise, while the probe saw their trip
  at or below their price. A timer expiry is no evidence that a price was unreal.
- Only two compared deals are known to be real while the probe was clearly higher (375, 414).
  The false-positive rate on cache deals therefore rests on 2 cases plus the control set.

### The honest gaps between the probe and the deal

- **Seller.** All 17 deals are sold by small agencies (Kiwi.com 5, Clickavia 5, Farera 5,
  Tickets 2). Google Flights lists mostly the airlines, and Kayak shows only the cheapest seller.
  An agency's real price can sit a few euros under both (414). This is the main reason for the
  € floor.
- **Carrier and airport.** The probe takes the cheapest nonstop of any carrier, so a higher
  probe price means no nonstop at the deal's price on any carrier. The probe's cheapest was
  another carrier than the deal's in 28 of the 91 searches made during the deals' lives (412: a
  Ryanair itinerary at 80 €, Wizz Air at 72–75 €). The airport never differed during a deal's
  life. It differed only in 415's searches from before its detection.
- **Rounding.** The cache and both engines give whole euros, Ryanair gives cents: ±1 €, inside
  the floor.
- **Nonstop, baggage:** no gap (above).

### Does the wanted list read open cache promotions often enough?

Yes, while the PC runs. Every cache deal that was open in the probe era was searched. For the
11 deals detected after 25/10 12:00, the first search came a median 5 h after detection
(1.5–8.3 h), and then a median 8.5 h between visits (6–24 h). The probe's outages are the exceptions: 408 waited 45 h across 01/11,
and Kayak missed some days after a wall. The cache deals lived 4.5–88 h (median 52 h), so a
probe-based expiry gets several chances in a typical life. The deals it would catch lived on
22–57 h after the probe first saw the higher price.

## Earlier claims, checked

- **Deal 412 at 58 € vs Google Flights 80 €: confirmed.** Google Flights showed 80 € on 02/11
  14:39, 8 h after detection (a Ryanair itinerary, seller Ryanair). Kayak showed 74 € in the same
  minute (Wizz Air). Later readings were 72–79 €. The rule would have expired it at 15:19, 57 h
  before the stale timer did.
- **Deal 417 at 42 € vs 63 €: confirmed.** Google Flights (seller easyJet) and Kayak both showed
  63 € on 10/11 19:24, 5 h after detection. The deal was still open and approved in the copy.
- **"3 of 14 compared promotions 10 %+ below the probe": not reproduced.** The copy has 17
  compared cache deals (6 approved, in 5 promotions). The number 10 % or more below the probe
  depends on the moment: 2 at the probe's first search (412, 417), 5 at its last search in the
  deal's life (163, 283, 408, 412, 417), 6 at any search (+415). Of the 214 compared Ryanair
  deals, none was 10 % below any search.

## Recommendation

**Ship it narrowly, for cache-source deals only:** expire when **both engines'** newest search,
**made after the deal's price was found**, **at the deal's arrival airport**, no older than
**12 h**, is at least **10 % and 5 €** above the deal's price.

- On this copy it fires on 5 of 17 compared deals: 163, 283, 408 (stale by Ryanair's own
  price), 412, 417 (unknown, circumstantially stale). 4 of them were approved and on the site.
  It fires a median 38 h before the real expiry (6.5–57 h).
- **False positives it costs: none measured.** On the cache deals, the two known real deals
  above the probe (375, 414) are outside the margin. On the control set, 0 of 214 Ryanair deals
  fire. The plateau is wide: ≥ 5 % up to ≥ 15 % with ≥ 5 €, at any age, give the same five deals.
- **Confidence: low to moderate.** It rests on 3 strong truths and 2 known real cases. The two
  unknown fires cannot be settled with the data we have. The control set says a 10 % gap does
  not occur against live prices. It does not test agency prices that Google Flights and Kayak
  do not list, and those are exactly the cache's sellers.
- Implementation notes for the decision (not done here): the rule belongs in the recheck of
  cache deals (`run_recheck`), never in the detector. It uses the comparison only in the
  conservative direction (to expire, never to confirm, so D47's rule stands). Its expiry needs
  its own pt-PT reason and an expiry kind the survival report can tell apart from the cache's
  own `gone` (D56). The review Function's live-check port would not see it (pipeline-only).
- **Rerun this preset after two or three more weeks of probe data** before you widen it.
  Watch for new control false positives and for new deals that are real and above the probe
  (the 375/414 pattern).

## How to rerun

```bash
# a copy of the database, never the live file (see the memory notes on store pull)
PYTHONIOENCODING=utf-8 uv run python scripts/backtest_detector.py <copy.db> --preset probe --json probe.json
uv run pytest tests/test_backtest_probe.py -q
```

The Markdown has, in order: the compared deals, every probe search from 24 h before
detection to the deal's end with its gap and the truth at that moment, the engine pairs, the
control line, the grid with the found-time guard, and the grid without it. `probe.json` has
the same data, with every fire (time, searches, truth) per rule.

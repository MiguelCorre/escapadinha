# Promotion outcomes: the first report (2026-11-03)

Status: first run of `escapadinha outcomes` (D56, #78) · Spec: #74
(`docs/specs/2026-11-03-promotion-outcomes.md`) · Research it reproduces:
`docs/research/2026-11-03-site-and-algorithm-improvements.md` §2.2–2.3

## How it was made

```bash
uv run escapadinha outcomes --days 30 --db <copy of the live database> --json out.json
```

On a copy of the live database (generation 604, 2026-11-03 20:26 UTC; downloaded with
`sync.remote_meta` + `sync._download` because the local file has diverged), opened read-only,
copied into memory and upgraded to schema v19 there. Thirty days take in every deal so far
(413, detected 2026-10-12 … 11-02). All but the one still open expired before v19, so their
expiry times are the backfill's (the last check before the expiry: exact for a recheck's
expiry, the previous recheck for a re-evaluation's) and their kinds come from their reasons.

## Against the research note

- **§2.2 is reproduced exactly:** 80 % of 361 judged deals gone within 24 h of detection;
  the Ryanair source 83 % of 342, the Travelpayouts source 21 % of 19; approved promotions a
  median 9.2 h from approval to expiry (38 deals). The report adds the other horizons: 19 %
  of deals are gone within 2 h, 41 % within 6 h, 93 % within 48 h.
- **§2.3 (date breadth) is not reproduced in its counts:** the note did not record its query.
  The report's definition is the note's sentence read literally (distinct departure dates on
  the deal's route, departure month and source at most 10 % above its price, seen in the 6 h
  before detection, its own date included; "seen" = first seen by detection and last seen
  after the window opened). Eight variants were tried on the same copy (its own date in or
  out, "seen" as above or first seen inside the window, departure dates or trips); none gives
  the note's 79 / 80 / 92 / 110 judged deals per band. **The conclusion holds in all eight:**
  deals with 0–3 dates around them were gone within 24 h less often (53–84 %) than deals with
  4 or more (85–92 %). Going's "many dates" rule does not transfer to our routes.
- **§2.4** is a different measure (median hours to the last check, every deal) but agrees in
  shape: 30–59 days of lead time 7.5 h both ways; found 12+ h before detection, the deals last
  far longer (47.7 h), the cache effect the note describes.

## What is new

- **Confidence matters more than it seemed:** at high confidence (D44) 55 % of 31 judged deals
  were gone within 24 h, against 83 % of 323 at medium. A small sample, but the first outcome
  measure of D44's split.
- **What the rules approved lasted longer** than what they left: 54 % gone within 24 h of
  detection (37 judged) against 83 % (324). From approval, 14 % were gone within 2 h and 70 %
  within 24 h.
- **Route kind makes no difference:** domestic and Europe both 80 % within 24 h.

Next runs: the same command after a few weeks of v19 data (exact expiry times), to compare
rule changes on outcomes (the spec's purpose). The review pages now print the 24 h share for
each queue item's source and confidence (#79).

## The report

Deals detected 2026-10-04 20:27 – 2026-11-03 20:27 UTC: 413, 1 still open. 412 of 413 expiry times are approximate (backfilled at schema v19 from the deal's last check).

"Gone ≤ x h": of the deals judged at x h, the share the recheck found gone (the price rose beyond the tolerance, the trip vanished, the price went stale) within x h; judged = gone by then, or watched at least x h. Open deals and superseded or rules expiries count as surviving until their last check, never as gone. "Median life": detection (or approval) to expiry, or to the last check while open.

Bands: lead time (found → departure, days) < 14, 14–29, 30–59, 60+; found age (exact found time → detection, h) < 2, 2–12, 12+; breadth (dates) 0–1, 2–3, 4–7, 8+. Breadth: distinct departure dates on the deal's route, departure month and source at most 10% above its price, seen in the 6 h before detection, its own date included.

## From detection

| Group | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| All | 413 | 19% of 406 | 41% of 393 | 80% of 361 | 93% of 343 | 7.5 |

### By source

| Source | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| ryanair | 385 | 20% of 380 | 43% of 369 | 83% of 342 | 95% of 328 | 7.0 |
| travelpayouts ¹ | 28 | 4% of 26 | 8% of 24 | 21% of 19 | 47% of 15 | 26.5 |

¹ The Travelpayouts source is a cache: it keeps prices travellers found earlier, which may already be gone at the airline, so its deals look longer-lived than they were bookable (research note 2026-11-03, finding 2).

### By confidence

| Confidence | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| high | 32 | 16% of 32 | 42% of 31 | 55% of 31 | 77% of 30 | 10.5 |
| medium | 368 | 20% of 363 | 41% of 352 | 83% of 323 | 94% of 308 | 7.5 |
| low | 0 | — | — | — | — | — |
| unknown | 13 | 9% of 11 | 20% of 10 | 29% of 7 | 100% of 5 | 13.5 |

### By approved by

| Approved by | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| rules | 38 | 11% of 38 | 32% of 37 | 54% of 37 | 75% of 36 | 13.8 |
| human | 0 | — | — | — | — | — |
| none | 375 | 20% of 368 | 42% of 356 | 83% of 324 | 95% of 307 | 7.5 |

### By lead time (days)

| Lead time (days) | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| < 14 | 2 | 0% of 2 | 0% of 2 | 100% of 1 | 100% of 1 | 17.8 |
| 14–29 | 45 | 24% of 45 | 48% of 44 | 79% of 43 | 90% of 42 | 6.0 |
| 30–59 | 364 | 19% of 357 | 40% of 345 | 80% of 316 | 93% of 300 | 7.5 |
| 60+ | 2 | 0% of 2 | 0% of 2 | 0% of 1 | — | 30.5 |

### By found age (h)

| Found age (h) | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| < 2 | 320 | 22% of 315 | 44% of 306 | 83% of 282 | 94% of 271 | 6.7 |
| 2–12 | 73 | 12% of 73 | 34% of 70 | 75% of 65 | 95% of 61 | 8.5 |
| 12+ | 8 | 0% of 8 | 0% of 8 | 25% of 8 | 33% of 6 | 47.7 |
| unknown | 12 | 10% of 10 | 22% of 9 | 33% of 6 | 100% of 5 | 11.5 |

### By route kind

| Route kind | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| domestic | 155 | 21% of 155 | 40% of 154 | 80% of 142 | 93% of 136 | 8.0 |
| europe | 258 | 18% of 251 | 41% of 239 | 80% of 219 | 93% of 207 | 7.2 |

### By breadth (dates)

| Breadth (dates) | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| 0–1 | 41 | 18% of 39 | 35% of 37 | 58% of 31 | 70% of 27 | 10.0 |
| 2–3 | 112 | 22% of 111 | 41% of 107 | 70% of 102 | 86% of 100 | 7.7 |
| 4–7 | 73 | 26% of 73 | 45% of 73 | 89% of 61 | 97% of 58 | 7.0 |
| 8+ | 187 | 15% of 183 | 40% of 176 | 87% of 167 | 100% of 158 | 7.5 |

## From approval (approved deals only)

| Group | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| All approved | 38 | 14% of 37 | 41% of 37 | 70% of 37 | 83% of 36 | 9.2 |

### By source

| Source | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| ryanair | 35 | 15% of 34 | 44% of 34 | 76% of 34 | 88% of 34 | 8.9 |
| travelpayouts ¹ | 3 | 0% of 3 | 0% of 3 | 0% of 3 | 0% of 2 | 71.9 |

¹ The Travelpayouts source is a cache: it keeps prices travellers found earlier, which may already be gone at the airline, so its deals look longer-lived than they were bookable (research note 2026-11-03, finding 2).

### By approved by

| Approved by | Deals | Gone ≤ 2 h | Gone ≤ 6 h | Gone ≤ 24 h | Gone ≤ 48 h | Median life (h) |
|---|---|---|---|---|---|---|
| rules | 38 | 14% of 37 | 41% of 37 | 70% of 37 | 83% of 36 | 9.2 |


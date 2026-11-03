# Spec: Promotion outcomes — how long our promotions stay bookable, measured every day

Status: draft for Miguel's decision · Origin: research of 2026-11-03
(`docs/research/2026-11-03-site-and-algorithm-improvements.md`, findings 1, 2, 3, 5 and section 2) ·
Milestone: M1 Data at scale · Vocabulary: `GLOSSARY.md` · Prior decisions: D40, D42, D44, D46, D47, D53

## Problem Statement

The detector's rules are measured before they ship (the backtest, D44), but nothing measures what
happens to the promotions after they ship. The research found that this is where the real story
is:

- **80 % of our deals were gone within 24 hours of detection** (361 judged; 83 % for the Ryanair
  source, which now produces 385 of the 413 deals). The 38 promotions approved so far stayed valid
  a median of 9.2 hours after approval.
- Rule changes (D44's new low, D46's automatic approval and its `medium` addendum, D52's stay
  lengths, D53's tolerance) were each argued on replays. None can be judged afterwards: was a
  promotion that the rules approved still bookable 6 hours later more often after the change than
  before?
- The database cannot answer that directly. An expiry stores no time: `db.record_recheck` sets
  `last_checked_at` on the expiring recheck, but `db.expire_deal` (the queue's re-evaluation,
  D40) leaves it at the previous recheck. And the reason is a pt-PT sentence with the price in it
  ("o preço subiu para 39,98 €"), so telling "the fare went away" from "a cheaper date replaced
  it" takes string matching.
- An idea from the competition does not survive our data. Going only publishes fares that hold on
  about ten departure dates. On our routes, a deal with more cheap dates around it does **not**
  last longer: 63 % were gone within 24 h with 0–1 such dates, and 85–91 % with four or more.
  Anything like this has to be measured on our own outcomes, not borrowed.

KAYAK states that it monitors its forecasts' accuracy daily, watching flights for the next seven
days against what it predicted. We should do the same for promotions.

## Solution

1. **Every expiry records when and why, in a form code can read.** Two nullable columns on
   `deals` (schema v19): `expired_at` (UTC) and `expired_kind`, one of a closed set
   (`outcomes.EXPIRY_KINDS`):
   - `gone`: the fare is no longer there at its source (price rose beyond the tolerance, trip
     vanished, price stale);
   - `superseded`: still there, but no longer a promotion by our rules because of other data (a
     cheaper date is now the new low, the typical low moved);
   - `rules`: the deal breaks a route rule that changed (nights range, D52; nonstop rule).

   Both writers set them: `db.record_recheck` (the recheck knows the kind of its verdict) and
   `db.expire_deal` (the re-evaluation, always `superseded` or `rules`). The human-readable reason
   stays as it is. A migration step backfills old rows: `expired_at` from `last_checked_at`
   (marked approximate in the report), `expired_kind` from the reason's known prefixes.
2. **A survival report**, pure and read-only: `outcomes.py` turns deal rows into survival tables
   (share gone within 2, 6, 24 and 48 hours of detection and of approval; median life; deals
   still open or superseded count as surviving until their last check, so they never inflate
   "gone"). Grouped by source, confidence, approved by (rules / human / not approved), lead-time
   band, found-age band, route kind, and date breadth (distinct cheap dates around the deal, as
   measured in the research). CLI `escapadinha outcomes [--days 14] [--json out.json]` on a
   read-only copy (`backtest.open_copy`), like the backtest.
3. **The reviewer sees the measured odds.** The review snapshot gains an optional `outcomes`
   line per queue item (the v1 snapshot exception: the Function reads the JSON as is): "Destas
   promoções (Ryanair, confiança média), 83 % desapareceram em 24 h (últimos 14 dias, 342)". A
   rate and a count, never a price.
4. **Optionally, the visitor too.** If Miguel wants it: one sentence on live promotion pages,
   from the same report, e.g. "Promoções destas costumam durar poucas horas: das últimas 38 que
   publicámos, metade ainda estava disponível 9 horas depois." Honest urgency, no countdown, no
   "reserva já" pressure. A rate, a count and hours: no price, so traceability is untouched, but
   the sentence is part of the contract and the fingerprint like anything the site shows.

## User Stories

1. As Miguel, I want every expired deal to say when it expired and whether the fare went away or
   was only replaced by a better one, so that I can tell a bad promotion from a superseded one.
2. As Miguel, I want a command that tells me, for the last N days, how many promotions were gone
   within 2, 6, 24 and 48 hours, by source, confidence and lead time, so that rule changes are
   judged on outcomes and not only on replays.
3. As Miguel, I want the report to treat a deal that was still open or only superseded as having
   survived until its last check, so that the numbers never overstate how fast fares vanish.
4. As Miguel, I want the report to include date breadth, found age and route kind, so that ideas
   like Going's ten-date rule can be tested on our data whenever the history is longer.
5. As Miguel, on the review page, I want to see how often promotions like this one vanished
   within a day, so that I know how much the "approve now" decision is worth.
6. As a visitor (if Miguel chooses it), I want an honest line on how long promotions like this
   usually last, so that I know whether to act today without being pressured.
7. As Miguel, I want old deals backfilled as well as possible and marked approximate, so that
   the report starts with three weeks of history instead of none.

## Implementation Decisions

- `outcomes.py` is pure (no I/O, no clock): rows and `now` passed in, like `detector.py`. Bands
  (lead-time, found-age, breadth) are constants in the module, listed in the report header.
- `EXPIRY_KINDS` is the only list of kinds; the SQL CHECK on `expired_kind` is tested against it
  (like `posting.CHANNELS`).
- Kinds come from the code path, never parsed from the pt-PT reason at run time. The prefix
  matching exists only inside the migration's backfill callable, with a test per known prefix
  (`recheck.py` and `pipeline.py` reasons as of v18).
- `recheck.recheck` returns its kind with its verdict (`Recheck.kind`); D53's tolerance and the
  nights-range check (D52) map to `gone` and `rules`.
- The snapshot line (item 3) is computed by `export_review_snapshot` from the report over the last
  `review.outcomes_days` days (config, default 14) for the item's source and confidence; with fewer
  than `review.outcomes_min_n` deals (default 20) it prints nothing.
- The visitor sentence (item 4), if chosen, is an additive field on `promotions.json` (`meta`
  level, not per promotion: one rate for all), recomputed only when the full path runs; it changes
  daily at most, so it is not a per-run field. pt-PT copy only in `format.ts`; numbers through
  `format.integer`.

## Testing Decisions

- Migration: upgrade from `tests/fixtures/schema_v5.sql`, `schema_v7.sql` and a v18 database with
  expired deals of each reason, asserting the backfilled kind per prefix and `expired_at` from
  `last_checked_at`.
- Pipeline seam: a recheck that expires a deal stores `expired_at` = the run's `now` and the right
  kind; a re-evaluation expiry stores its own time (not the previous recheck's).
- `outcomes.py`: survival with censoring on hand-made rows (open, superseded, gone at 3 h, gone at
  30 h), grouping, empty groups, the approximate flag.
- CLI on a `tmp_path` database; refuses to write (opens read-only).
- Snapshot: the optional field validates against nothing new (v1 exception) and the Function's
  page renders with and without it (`web/test/review/page.test.ts`).

## Out of Scope

- Changing any detector rule. This spec measures; rule changes stay separate decisions, measured
  with the backtest and then with this report.
- A minimum number of departure dates per promotion (measured against in the research).
- Buy-or-wait prediction (finding 4).
- Faster rechecks of the Ryanair source: D47's rules (one plain request at a time, a bounded hot
  list) stay.

## Further Notes

- The research's numbers are from generation 600 (2026-11-03). The first run of the report
  should reproduce section 2.2 of the research note within rounding (approximate expiry times for
  old rows).
- The Travelpayouts source's apparent long life (21 % gone within 24 h) is partly the cache
  keeping prices that may already be gone: the report should print it, and the research note's
  caveat, side by side with the Ryanair source.

## Tickets

Spec issue #74. Tickets (opened 2026-11-03, `needs-decision`):

1. #77 M1 Record when and why every deal expires (`expired_at`, `expired_kind`, schema v19)
2. #78 M1 Promotion outcomes report: survival by source, confidence, lead time, found age and breadth
3. #79 M1 Show the measured survival on the review pages (and, if chosen, on promotion pages)

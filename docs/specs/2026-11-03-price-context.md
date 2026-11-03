# Spec: Price context on the site — a plain verdict, the hour it was found, a home page that leads with what is live

Status: draft for Miguel's decision · Origin: research of 2026-11-03
(`docs/research/2026-11-03-site-and-algorithm-improvements.md`, findings 2 and 6, section 2.5) ·
Milestone: M3 Website · Vocabulary: `GLOSSARY.md` · Prior decisions: D24, D30, D35, D40, D44, D46, D53

## Problem Statement

A visitor on a route page sees "Mais barato agora: 98 €" and, further down, a table of typical
lows per month. Whether 98 € is good is left to them to work out. Google Flights answers that
question in three words ("low", "typical", "high" for the route), and only for searches where it
has reliable trend data. We have the ingredients for the same answer (the typical low per route
and month, the maturity gate, D40, and the confidence level, D44) but do not say it.

Two more problems were visible on the live site on 2026-11-03:

- **Time.** Our promotions are short-lived: the 38 approved so far stayed valid a median of 9.2
  hours, and error fares elsewhere last hours (Jack's Flight Club, Going). Yet cards and pages say
  only the day a traveller found the price ("Encontrado por um viajante a 01/11/2026"), although the
  exact time is known for most offers (GraphQL `found_at`, D43; the airline's `priceUpdated`, D47)
  and the review pages already print it ("encontrado a 24/10/2026 às 13:05 (há 1 h 20)", D46).
- **The home page.** It showed 1 live promotion followed by 28 expired ones, 19 of them Lisboa →
  Madeira. The expired list has no cap (everything from the last `site.expired_promotions_days`,
  30). The one thing a visitor can book is lost in a wall of things they cannot. `/promos/` is a
  404, so there is no place where the full record lives.

## Solution

1. **A price verdict** next to "Mais barato agora" on route pages and next to the price on live
   promotion pages: "Preço baixo para dezembro", "Preço habitual para dezembro" or "Preço alto
   para dezembro", followed by the typical low it was judged against ("mínimo habitual 100,50 €",
   on its `data-route`). Shown only when that departure month's typical low is mature
   (`detector.is_mature`) and its confidence is at least `medium` (D44); otherwise nothing (no
   "sem dados" badge). The rule is ours and simple, so the page can explain it in one line:
   - **baixo**: the price qualifies as a low price (`≤ typical low × (1 − low_threshold)`, the same
     rule as the low-price tier, D24);
   - **alto**: the price is at least `price_insight.high_margin` above the typical low (config,
     proposed 25 %);
   - **habitual**: in between.
2. **The hour a price was found**, on promotion cards, promotion pages and low-price rows:
   "encontrado a 01/11 às 13:05", Lisbon time, from the observation's exact found time when it is
   known (the day only, as today, when it is not). A few lines of our own script turn it into "há
   2 h" in the visitor's browser (no third party, no cookie, no request); without the script the
   absolute time stays. The build never writes a relative time, so it is not a per-run field.
3. **A home page that leads with what is live.** Expired promotions shrink to one card per route
   (the most recent), at most `site.home_expired_max` cards (proposed 6), each with "+ N
   promoções nesta rota nos últimos 30 dias" linking to the route page. A new page `/promos/`
   lists every live promotion and every expired one still kept (`site.expired_promotions_days`),
   grouped by route, newest first: the record of what we found, with each price on its
   `data-obs`.

## User Stories

1. As a visitor, I want to read in three words whether the cheapest price on a route is low,
   typical or high for that month, so that I do not have to compare it with a table myself.
2. As a visitor, I want the verdict to say which typical low it was judged against, so that I
   can check the claim.
3. As a visitor, I want no verdict at all when the site does not have enough history, so that
   the site never sounds surer than its data.
4. As a visitor, I want to see the hour a price was found and how long ago that was, so that I
   know a 9-hour-old fare may already be gone.
5. As a visitor on the home page, I want the live promotions first and the expired ones reduced
   to a short summary per route, so that I see what I can book.
6. As a visitor, I want one page that lists every promotion found in the last month, live and
   expired, grouped by route, so that I can judge the site's track record.
7. As Miguel, I want the verdict thresholds in config and measured on the backtest's data before
   they ship, so that "baixo" means the same as the low-price tier and "alto" is a measured choice.

## Implementation Decisions

- **Contract (additive within v1, D27):** `routes.json` `months[]` gains `confidence`
  (`low | medium | high | null`, from `detector.confidence` on the same baseline the export already
  computes); `meta.detector` gains `high_margin`; the offer definition (`defs.schema.json`) gains
  `found_at` (UTC timestamp or null). No new price field, so the traceability checker needs no new
  rule; the verdict's typical low is the existing `typical_low` on its `data-route`. Schemas,
  `site_data.py` and the fixtures change together; the fixtures are regenerated with `escapadinha
  export fixtures` if the export is reproducible, else edited by hand for these additive fields
  only, said in the DECISIONS entry (CLAUDE.md's rule).
- **Verdict logic** in one pure module, `web/src/lib/price-insight.ts` (`verdict(price, month,
  detector) → "baixo" | "habitual" | "alto" | null`), used by the route page and the promotion
  page; copy only through `format.ts` (`format.priceVerdict`), month names included. A Python twin
  is not needed: posts are paused (D46) and captions keep D44's claim rules.
- **Found time:** `format.foundAt(found_at, found_date)` prints the absolute Lisbon time or the
  day; the relative upgrade is one small inline script, shared by the cards, that reads a
  `data-found-at` attribute. The privacy page needs no change (no request, no storage).
- **Home and `/promos/`:** the grouping lives in `src/lib/promotion.ts` (one function, used by
  both); `/promos/` has a stable key in `website/routing.current_pages` and is indexed when it
  lists at least one live promotion, else `noindex` (it then shows only expired ones, as their
  pages do). JSON-LD: an `ItemList` of the live promotions only, through `structured-data.ts`; no
  Offer for an expired promotion (D34).
- **Fingerprint:** every new contract field is part of `site_data`; none changes every run (the
  verdict follows `cheapest`, which is already in the contract).

## Testing Decisions

- `web/test/price-insight.test.ts`: the three bands at their edges, immature month, `low`
  confidence, missing typical low; the copy for each.
- Route and promotion pages built from the fixtures show the verdict where the fixture month is
  mature and medium or high, and nothing elsewhere (`web/test/pages.test.ts`), with the typical
  low on its `data-route` (`web/test/traceability.test.ts`).
- `format.test.ts`: `foundAt` with and without an exact time, Lisbon time across the DST change;
  no month names outside `format.ts` (existing test).
- Home: one card per route among expired ones, the cap, the "+ N" link; `/promos/` lists
  everything kept, grouped, and is `noindex` when nothing is live (`web/test/seo.test.ts`).
- `tests/test_site_data.py`: the new fields validate, `confidence` equals `detector.confidence`
  for the month, `found_at` equals the observation's.

## Out of Scope

- "Quando reservar" (best time to book) notes: our lead times are 30–59 days for 88 % of deals;
  revisit when the outcomes report (spec of the same day) covers wider lead times.
- Price prediction or "vai subir" copy (research finding 4).
- A verdict in posts and captions (publishers paused, D46; D44's claim rules stand).
- Any change to what a low price or a promotion is.

## Further Notes

- Google's typical range is built from years of market-wide data; ours from daily lows over a
  short window. The page's one-line explanation must say so in plain words ("comparado com o
  mínimo habitual que medimos nesta rota para esse mês").
- The proposed 25 % for `high_margin` is a starting point: the ticket checks, on the backtest's
  database copy, how often each band would have been shown in the last 14 days and reports it
  before shipping.

## Tickets

Spec issue #75. Tickets (opened 2026-11-03, `needs-decision`):

1. #80 M3 Price verdict (baixo / habitual / alto) on route and promotion pages
2. #81 M3 Show the hour a price was found, with a "há x h" upgrade in the browser
3. #82 M3 Home leads with live promotions; `/promos/` lists the month's record by route

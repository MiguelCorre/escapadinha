# Improvements for the deals algorithm, the site, SEO and monetisation

Research of 2026-11-03, asked by Miguel ("investiga melhorias e features que podíamos adicionar no
nosso site e algoritmo de deals; vai criando specs"). Research only: no code changed. Two parts:

1. A multi-source web research run (5 search angles, 22 sources fetched, 83 claims extracted, 25
   checked by three independent verifiers each, 21 confirmed, 4 refuted). Only confirmed claims
   are used below, with their sources.
2. Measurements on a read-only copy of the live database (generation 600, last run #1898, pulled
   from R2 on 2026-11-03 into a scratch folder; `data/escapadinha.db` was not touched) and on the
   live site, to check each claim against our own data before it becomes a spec.

**Builds on** [`2026-10-15-more-data-and-site-ideas.md`](2026-10-15-more-data-and-site-ideas.md)
(sources, deferias.pt comparison, T1–T5: baggage, backtest, Eurostat, school holidays, alerts),
[`2026-10-18-detector-backtest.md`](2026-10-18-detector-backtest.md) and
[`2026-10-24-faster-deal-discovery.md`](2026-10-24-faster-deal-discovery.md). What those settled is
not repeated. The constraints are the same (CLAUDE.md: no scraping, no fabricated prices, links
only from the partner-links API, no cookies, scripts only on a click, free tiers).

**Specs opened from this note:**

| Spec | What | Milestone | Issues |
|---|---|---|---|
| [`2026-11-03-promotion-outcomes.md`](../specs/2026-11-03-promotion-outcomes.md) | Record when and why every deal expires; a survival report by source, confidence, lead time and age | M1 | spec #74; #77, #78, #79 |
| [`2026-11-03-price-context.md`](../specs/2026-11-03-price-context.md) | A low / typical / high verdict next to prices, the hour a price was found, a home page that is not drowned by expired cards | M3 | spec #75; #80, #81, #82 |
| [`2026-11-03-index-pages-with-data.md`](../specs/2026-11-03-index-pages-with-data.md) | Route pages and destination hubs without data of their own leave the index (noindex, out of the sitemap), keep working | M3 | spec #76; #83, #84 |

---

## 0. The headline

- **Our promotions are short-lived, and the data says why.** Of the 361 deals that can be judged
  at 24 h, **80 % were gone within 24 h of detection** (price rose, trip vanished or price stale).
  For the Ryanair source (D47), which now produces 385 of the 413 deals, it is 83 %; for the
  Travelpayouts cache 21 % (19 judged, and the cache keeps prices that may already be gone). The
  38 promotions approved so far (all by the rules, D46) stayed valid a **median 9.2 h** after
  approval. Nothing in the database records this directly: there is no expiry time and the reason
  is free text. Spec 1.
- **Going's "at least ten dates" rule does not transfer.** Going publishes a fare only when it
  holds on many departure dates (finding 1). On our data, a deal with more cheap dates around it
  does **not** last longer: gone within 24 h for 63 % of deals with 0–1 such dates, 76 % with 2–3,
  91 % with 4–7, 85 % with 8+. Ryanair seems to reprice a whole month at once. Not a gate; kept as
  a dimension of the survival report, to look at again as history grows.
- **Price prediction ("compra já ou espera") is not worth building.** The whole gain of perfect
  timing is about 11 % of the fare in the literature and the best models capture 62–65 % of it,
  on long per-flight histories we do not have (finding 4).
- **A plain verdict next to a price is what the big platforms show** (Google Flights: low, typical
  or high, only where trend data is reliable, finding 6). We have the ingredients (typical low,
  maturity, confidence). Spec 2.
- **Indexed pages without data are an SEO risk.** Google's doorway and scaled-content policies
  judge purpose and value, not templating (finding 7). **108 of our 375 indexed route pages have
  never had a price**, and 35 of 158 destination hubs have no route with a price. Spec 3.
- **Monetisation: traffic is the lever, not a paid tier.** Aviasales pays about 1 % of the ticket
  (finding 8), credited for 30 days, last click (finding 9); Jack's Flight Club, a paid deals
  club, has flat subscribers and thin margins (finding 10). No spec: the SEO spec is the
  monetisation work.

---

## 1. Verified findings (web research)

Each finding carries the verifiers' vote (three independent verifiers; two refutes kill a claim)
and its primary sources. "Our data" lines are this note's own measurements (section 2).

### 1. Going requires a deal to hold on many dates (high, 3-0)

Going's membership guide (updated 2026-06-03, "How we decide what makes a deal", "What kind of
availability is there?") says it never sends a deal available for only one set of dates and
"typically, we look for at least ten departure dates". Availability is one of five criteria, and
Going may accept a slightly higher price in peak periods.
**Our data:** promotions (D53, since 2026-10-28) hold one deal each in most cases (29 promotions,
the largest six dates); and date breadth does not predict survival (section 2.3). **Verdict:** no
minimum-dates gate. Spec 1 reports survival by breadth so the question can be re-asked later.
Source: https://going.com/guides/membership-guide

### 2. Error fares last hours; publish on fresh prices (medium, 2-1)

Jack's Flight Club's help page (updated 2026-02-06) says error fares "may last only a few hours"
and most other deals a day or two; Going's mistake-fares guide says minutes to several hours.
Travelpayouts' cache keeps found prices for days, so the risk is publishing a fare that has gone.
**Our data:** the automatic approval already refuses a price found more than 48 h earlier
(`review.auto_approve.max_found_age_hours`, D46); the median found age at approval was 1.4 h
(p90 24.9 h). **Verdict:** the gate exists; what is missing is showing the found time to the hour
(spec 2) and measuring survival by found age (spec 1). Refuted alongside (0-3): that "a day or
two" is a benchmark for how long a promotion page should stay live.
Sources: https://jacksflightclubhelp.helpscoutdocs.com/article/95-how-long-will-the-deals-last ,
https://going.com/guides/mistake-fares

### 3. Lead time and booking weekday matter, but not as simple rules (medium, 3-0)

Groves & Gini (ACM TIST 2015; 109 days of 2011 US queries) see prices rise in the last 7 days
before departure; Piga & Bachis (Loughborough working paper, 2006, ~650 000 European low-cost and
full-service fares) find fares that do not rise monotonically and higher volatility in the last
four weeks. The booking-weekday effect depends on the route and the airline and is small.
**Our data:** 364 of 413 deals had a lead time of 30–59 days, 2 under 14: too narrow to test
lead-time bands. **Verdict:** keep D44's `baseline_min_lead_days`; no "reserva à terça" copy and
no "reserva já antes que suba" copy. Spec 1 reports survival by lead-time band.
Sources: https://www-users.cs.umn.edu/~gini/papers/Groves2015tist.pdf ,
https://dspace.lboro.ac.uk/dspace-jspui/bitstream/2134/2293/3/piga_2006.pdf

### 4. Buy-or-wait prediction is a weak investment (high, 3-0 ×4, 2-1)

Groves & Gini: optimal timing saves 11.0 % over buying at once; their model reaches 7.25 %
(Table VII mean efficiency 64.8 %). Etzioni et al., "To Buy or Not to Buy" (KDD 2003): 61.8 % of
optimal, 4.4 % of the ticket price over 4 488 simulated passengers (a pilot: 2 routes, 41 days).
Huang, Chen & Schwartz (J. Revenue and Pricing Management, 2019): "no best website" among
commercial predictors, accuracy varies with days before departure. KAYAK's forecast is only a
7-day up-or-down call with a confidence level. All rely on long per-flight histories; we have
about a week of cached prices per route. **Verdict:** not now. If ever, copy KAYAK's narrow form
and backtest it first. Refuted (0-3): that a simple historical-minimum rule nearly matched
Etzioni's model.
Sources: https://www-users.cs.umn.edu/~gini/papers/Groves2015tist.pdf ,
https://www.stat.berkeley.edu/~aldous/157/Papers/etzioni.pdf ,
https://digitalscholarship.unlv.edu/hotel_fac_articles/269 ,
https://www.kayak.com/c/help/pricing/how-does-kayak-price-forecast-work.62022.faq

### 5. Score published deals forward, not only in replay (high, 3-0)

KAYAK's help page: "We monitor and measure daily the accuracy of our predictions", tracking a set
of flights over the next seven days and checking the forecast against the outcome (no figures
published). **Our data:** the recheck already judges every open deal every run (D42), but an
expiry stores neither its time nor a machine-readable kind (`db.expire_deal` leaves
`last_checked_at` at the previous recheck; reasons are pt-PT sentences). **Verdict:** spec 1.
Source: https://www.kayak.com/c/help/pricing/how-does-kayak-price-forecast-work.62022.faq

### 6. A low / typical / high verdict where trend data is reliable (medium, 2-1 and 3-0)

Google's blog (2023-08-28) shows "whether current prices for your search are low, typical or high
compared to past averages for the same route" and, "for searches with reliable trend data", when
prices have usually been lowest to book; both still live in Google's 2025 holiday post. Google's
typical range comes from years of market-wide data; ours from daily lows over a short window, so
the method is only loosely comparable. No source measured the effect on traffic or conversion.
**Our data:** route pages show "Mais barato agora" and a table of typical lows per month, no
verdict. **Verdict:** spec 2, behind `detector.is_mature` and confidence ≥ medium (D44). The
"when to book" note waits: our lead-time range is too narrow (finding 3).
Source: https://blog.google/products/travel/google-flights-find-deals/

### 7. Doorway and scaled-content policies are the SEO risk of programmatic pages (high, 3-0 ×4)

Google's spam policies list as doorway abuse "Creating substantially similar pages that are closer
to search results than a clearly defined, browseable hierarchy" and pages targeted at cities or
regions that funnel users to one page; as scaled content abuse, many pages "without adding value
for users", "no matter whether content is produced through automation, human efforts, or some
combination" (Search Central, 2024-03-05). The test is purpose and value: additional price
information and useful navigation count as value. Refuted (1-2): that pages differing only by city
name are exactly what the policy targets. **Our data:** 560 URLs in the sitemap; 375 route pages
(108 never had a price, so they say only "Não há preços recentes nesta rota"), 159 destination
hubs (35 destinations with no route that ever had a price, e.g. `/destinos/katowice/`, indexed).
**Verdict:** spec 3. Reviewed MDX (D33) should keep adding original, sourced material.
Sources: https://developers.google.com/search/docs/essentials/spam-policies ,
https://developers.google.com/search/blog/2024/03/core-update-spam-policies ,
https://developers.google.com/search/blog/2015/03/an-update-on-doorway-pages

### 8. Aviasales pays about 1 % of the ticket (high, 3-0)

Travelpayouts' programme page: "On average, you will receive 1.1% of the ticket price, which is
40% of the 2.2% commission Aviasales gets" (its own arithmetic gives 0.88 %), and elsewhere
1.1–1.3 %; Partnerkin (2026-04-30) reports the same 40 % share. On short-haul fares from Portugal
that is in the order of one or two euros per booking (our arithmetic, not the source's).
**Verdict:** volume of qualified visits matters more than per-click tuning: spec 3 first.
Source: https://travelpayouts.com/en/offers/aviasales-affiliate-program

### 9. Bookings are credited for 30 days after the click, last click wins (medium, 2-1)

The same page lists a 30-day cookie lifetime, counted from the first visit to Aviasales; the
Travelpayouts glossary credits the last affiliate link clicked. The cookie is the partner's,
after the click; our site sets none (CLAUDE.md), and the route pages already say the partner may
use its own cookies once the visitor opens its search. **Verdict:** nothing to change.
Source: https://travelpayouts.com/en/offers/aviasales-affiliate-program

### 10. A paid membership tier is a poor model for us (high, 3-0 ×2)

Travelzoo's Q4 2025 release (2026-02-19): Jack's Flight Club revenue +2 % to 1.3 M USD, "The
number of premium subscribers remained flat"; full-year 2025 operating profit 341 k USD on
5 371 k USD revenue (about 6 %). Q3 2026 (2026-10-27): revenue −15 %. **Verdict:** stay free,
affiliate-funded (spec v2 unchanged); a paid tier would also bring payments and subscriber data
under GDPR.
Source: https://s201.q4cdn.com/362028750/files/doc_financials/2025/q4/Travelzoo-February-19-2026.pdf

### Gaps

No claim survived about Secret Flying, Holiday Pirates/Urlaubspiraten, Fly4free/deferias.pt (see
the 2026-10-15 note for deferias), Skyscanner Explore or its alerts, Hopper's methods or Kiwi
Nomad. No source measured the traffic, conversion or retention value of any feature (badges,
explorer, alerts). The academic evidence is old, mostly US, and never on cached user-searched
prices: every transfer to our routes is a hypothesis, which is why section 2 exists.

---

## 2. Measurements on our data

Read-only SQL on the database copy (generation 600, 2026-11-03), through the project's own
`ObjectStore`; the live site read as a visitor the same day.

### 2.1 What we have

| Measure | Value |
|---|---|
| Deals | 413, detected 2026-10-12 … 11-02; 412 expired, 1 approved (live) |
| Approved | 38, all by the rules (`aprovação automática (D46)`), none by hand |
| Source of the deal's observation | Ryanair 385, Travelpayouts 28 |
| Confidence at detection (D44) | medium 368, high 32, none 13 (before D44) |
| Promotions (D53, since 2026-10-28) | 29, one open; deals per promotion: mostly 1, at most 6 |
| Expiry reasons (412 expired) | price rose 240, trip vanished 83, "já não é um novo mínimo" 67, stale 9, typical low not mature 7, no longer below the typical low 4, nonstop rule 1, nights range 1 |
| Observations | 78 760: Ryanair 61 003, Travelpayouts 15 504, Google Flights 1 424, Kayak 829 |

### 2.2 How long deals stay valid

"Gone" = expired because the price rose, the trip vanished or the price went stale (the recheck,
D42/D53). A deal superseded by a cheaper one ("já não é um novo mínimo") or still open is not
gone: it counts only once it has been watched for 24 h. Time is measured from detection, to the
deal's last check (`last_checked_at`, the closest the database has to an expiry time).

| Group | Deals | Judged at 24 h | Gone within 24 h |
|---|---|---|---|
| All | 413 | 361 | 80 % |
| Ryanair source | 385 | 342 | 83 % |
| Travelpayouts source | 28 | 19 | 21 % |

Approved promotions: median **9.2 h** from approval to their last check (p10 1.5 h, p90 72 h, 38
deals). When they expired because the price rose, the rise was a median +5.3 % (p10 +2.2 %,
p90 +9.6 %; 31 deals; D53's 5 % tolerance arrived on 2026-10-28, mid-sample).

### 2.3 Date breadth (Going's rule) against survival

Breadth = distinct departure dates on the same route, departure month and source with a price at
most 10 % above the deal's, seen in the 6 h before detection.

| Breadth | Judged at 24 h | Gone within 24 h |
|---|---|---|
| 0–1 dates | 79 | 63 % |
| 2–3 | 80 | 76 % |
| 4–7 | 92 | 91 % |
| 8+ | 110 | 85 % |

More cheap dates around a deal do not make it last longer here; if anything the reverse.

### 2.4 Lead time and found age

Here every deal counts, whatever ended it, from detection to its last check.

| Lead time (found → departure) | Deals | Median hours to last check |
|---|---|---|
| < 14 days | 2 | 17.8 |
| 14–29 | 45 | 5.5 |
| 30–59 | 364 | 7.5 |
| 60+ | 2 | 29.7 |

| Found age at detection (exact found time known) | Deals | Still open 24 h after detection |
|---|---|---|
| < 2 h | 309 | 13 % |
| 2–12 h | 79 | 22 % |
| 12 h + | 13 | 54 % |

The few older-found deals that "survive" are mostly cache prices that the cache keeps, not
proof that they were bookable (finding 2). Samples outside 30–59 days are too small to say more.

### 2.5 The site, read on 2026-11-03

- Sitemap: 560 URLs (375 `/voos/`, 159 `/destinos/`, 7 `/partidas/`, the rest content and
  utility pages). Route pages and hubs never set `noindex` (only promotions, ponte pages, content
  drafts and empty listings do).
- 108 routes have no observation at all (`routes.last_observed_at` null); 219 were observed in the
  last 7 days. A never-observed route page (`/voos/faro-katowice/`) says "Não há preços recentes"
  in every section and is in the sitemap; so is its hub `/destinos/katowice/`.
- The home page showed 1 live promotion and 28 expired ones, 19 of them Lisboa → Madeira; the
  expired list has no cap (`site.expired_promotions_days` 30). `/promos/` is a 404.
- Promotion cards and pages print the found **day** ("Encontrado por um viajante a 01/11/2026");
  the review pages already print the hour and the age (D46).

---

## 3. What was not turned into a spec, and why

| Idea | Why not now |
|---|---|
| Minimum number of departure dates per promotion (Going) | Measured: breadth does not predict survival on our routes (2.3) |
| Buy-or-wait prediction, "preço vai subir" | Small gain even with long histories (finding 4); we have a week of cache |
| "Quando reservar" note on route pages | Our lead times are 30–59 days for 88 % of deals (2.4): nothing to advise on yet. Re-ask once spec 1's report covers wider lead times |
| Booking-weekday copy | Route- and airline-dependent, small (finding 3) |
| A paid tier, a members' club | Finding 10 |
| Error-fare hunting as a feature | Error fares last hours; a cache that keeps prices for days shows them late (finding 2) |
| More affiliate tuning | About 1 % per booking (finding 8): traffic first (spec 3) |

---

## 4. Refuted claims (not used)

| Claim | Vote | Source |
|---|---|---|
| Going uses no fixed discount threshold and needs a bigger drop on routes that rarely go on sale | 0-3 | going.com membership guide |
| "A day or two" is a benchmark for how long a promotion page should stay live | 0-3 | Jack's Flight Club help |
| A simple historical-minimum rule nearly matched Etzioni's model | 0-3 | Etzioni et al. 2003 |
| Pages differing only by city name are exactly what Google targets | 1-2 | Search Central 2024-03 |

---

## Appendix: how this was done

- Web research: the `deep-research` workflow (5 search angles: competitor practice, academic
  anomaly and buy-or-wait work, big-platform price insights, pt-PT SEO and programmatic pages,
  monetisation), 104 agent calls; claims verified by three agents each.
- Database: `sync.remote_meta` + `sync._download` into a scratch file (the documented `store pull`
  refused because the local copy had local changes since generation 67; it was left alone), then
  read-only SQLite (`mode=ro`).
- Site: pontonomada.pt read in the built-in browser (home, `/partidas/`, `/voos/lisboa-paris/`,
  `/voos/faro-katowice/`, `/destinos/katowice/`, `/sitemap.xml`, `/promos/`).

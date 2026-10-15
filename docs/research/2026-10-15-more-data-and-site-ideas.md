# More flight-price data and ideas for the site

Research for issue #39 (M1). Date: 2026-10-15. Research only: no code changed. Every price
mentioned here was read from an API answer or from a database copy during the probes described in
the appendix; nothing here is published.

**Builds on** [`2026-10-15-data-reliability.md`](2026-10-15-data-reliability.md) (merged as PR #40
while this one was written). That report settled, with evidence, the questions inside the
Travelpayouts Data API: send `direct=true` on direct-only routes (2–3× the usable observations),
raise maturity to ≥ 10 daily lows over ≥ 9 days with ≥ 2 departure dates per day (7 of the 11
deals so far were not really −30 %), show the baseline to the reviewer, fetch months 4–6 once a
day, keep 2 h but make the cron reliable, and add no other REST endpoint (same cache). **This
report takes those as given** and does not repeat them. It adds what that one left out: the
GraphQL endpoint (untested there), the `market` parameter, every source outside Travelpayouts,
public demand data, baseline ideas beyond the day-count rules (dispersion, lead time, weekday,
new-low, confidence as words), the deferias.pt comparison and the site ideas. Where the two touch,
the text says "see data-reliability".

**Constraints every recommendation respects** (issue #39, CLAUDE.md, D13, D19, D34): no scraping
of booking sites or airlines; no fabricated prices (estimates only inform detection, never a
page); affiliate links only from the Travelpayouts partner-links API; the site sets no cookies and
loads third-party scripts only on a click; GitHub Actions and Cloudflare free tiers. Section 5
checks each recommendation against them.

---

## 0. Ranked recommendations

Value is for the traveller first and for the reliability of our promotions second. Effort is
agent work (S ≤ half a day, M one to two days, L more). Cost is running cost. Risk covers terms,
data quality and the chance the work is wasted.

Rank 0 is the data-reliability report's own list (`direct=true`, stricter maturity, baseline shown
to the reviewer, daily months 4–6, reliable cron): do it first, it is the biggest reliability
gain available and needs no new source. The rest is new here.

| # | Recommendation | Value | Effort | Risk | Cost | Needs an account? |
|---|---|---|---|---|---|---|
| 0 | **Apply data-reliability items 1–5** (see that report; its item 1 touches `request_params` and the live-check cases on both sides) | High | M | Low | 0 € | No |
| 1 | **Enrich candidates and low prices through the Aviasales GraphQL API**: baggage allowance, selling agency, exact found time; same token, same cache, same terms (A1, ticket T1) | High (the "c/ mala de porão" line travellers compare on) | M | Low | 0 € | No (token already set) |
| 2 | **A committed backtest harness plus three rules on top of the new maturity gate**: confidence as words, a "new low" condition for promotions, lead-time-aware baselines (section 3, T2) | High (fewer false promotions, measured) | M | Low | 0 € | No |
| 3 | **Rank routes by real demand with Eurostat `avia_par_pt`** (monthly passengers per airport pair, reuse allowed with attribution): order pages and the explorer, pick which routes get the daily months 4–6 pass, explain thin routes (A12, T3) | Medium-high | S | Low | 0 € | No |
| 4 | **School-holiday planner ("férias escolares") next to pontes**: the official calendar as data, a pure window rule, explorer filter and pages (B, T4) | High for families | M | Low | 0 € | No |
| 5 | **Low-price alerts: daily per-origin Telegram digests and a weekly e-mail digest** (Buttondown, privacy-first, free to 100 subscribers) (B, T5) | High (deferias' strongest retention tool) | M | Low-medium | 0 € now | Buttondown account (Miguel) |
| 6 | Use Aviasales' own `special_offers` and GraphQL `discount` as a **cross-check signal** in review (never displayed) (A2) | Medium | S | Low | 0 € | No |
| 7 | Small site wins copied from deferias: origin chips on the home page, a partnerships page, "paga-nos um café", airline guides as tips (B) | Medium | S each | Low | 0 € | Ko-fi or similar for the coffee link |
| 8 | Skyscanner affiliate programme: revisit at 5 000 unique visitors/month (links only, no data; D13 unchanged) (A6) | Low now | S | Medium | 0 € | Yes, later |
| 9 | AeroDataBox schedules (which airlines fly a route, how often): only if a "quem voa" line is wanted; paid plan from about 8 USD/month, 7-day storage limit (A14) | Low | M | Medium | ~8–40 USD/month | Yes |

**Not recommended (and why, one line each; details in section 2):** Aviasales Search API
(50 000 MAU, and scraping its results is forbidden), Kiwi.com (invitation-only since 2024-05;
through Travelpayouts also 50 000 MAU), Duffel (its Services Agreement forbids metasearch,
republishing and marketing with fares), Amadeus Self-Service (decommissioned 2026-07-17), Google
Flights (no API; automated access forbidden by its terms), airline sites (no feeds; scraping is
D13), Kayak price insights (price data gated behind its own affiliate network, links would not
come from Travelpayouts), OpenSky (non-commercial, no schedules), ANAC and ANA (terms forbid
reuse), other Aviasales markets (probed: same cache, no extra routes).

**The honest headline:** no legitimate source gives Portugal's thin routes more price history
than the Aviasales cache already does. The cache holds about eight days of found prices per route
and only for routes that Aviasales users actually search. Reliability therefore comes from (a)
asking the cache the right way and keeping our own history (rec. 0, already decided), (b) rules
calibrated on a backtest (rec. 2), (c) richer fields for the prices we have (rec. 1) and (d)
knowing which routes matter (rec. 3), not from a new provider.

---

## 1. Where the data stands today (database copy, generation 46, 2026-10-15 22:24 UTC)

Read-only queries on `data/escapadinha.db` after `store pull` (one run newer than the
data-reliability report's copy); maturity computed with `detector.month_baselines` and the real
config. The counts agree with that report (276 route-months with usable rows, 30 mature at ≥ 4
days, 4 at ≥ 7, 17 routes with a mature month), so they are not repeated. What is new here:

| Measure | Value |
|---|---|
| Observations | 4 073; `found_date` 2026-10-05 … 2026-10-15; nonstop both ways 1 491 (37 %) |
| Routes with at least one price, by origin | LIS 104/111, OPO 82/108, FAO 28/67, FNC 19/49, PDL 4/17, TER 2/8 (121 of 360 none) |
| Airlines (observations) | FR 1 534, U2 494, TP 431, VY 252, W4 166, EC 139, UX 93, S4 89 |
| Persistence | 209 observations seen in one run, 3 490 in five or more |

Two facts shape everything below:

- **The cache is shallow in days, not in offers.** For Lisbon–Paris, November 2026, nonstop, 2–10
  nights, `prices_for_dates` returns 46 offers on 46 distinct date pairs, found on 8 distinct days
  (2026-10-08 … 10-15). The GraphQL endpoint returns 466 rows for the same question, but they are
  the same 36 trips sold by several agencies (City.Travel, Kiwi.com, Farera, Mytrip, Flightnetwork),
  found on the same 8 days. No endpoint gives a ninth day. The baseline grows one day per day of
  our own collection, and only for routes someone searches on Aviasales.
- **Normal variation is large relative to our thresholds.** In the 30 mature route-months the
  coefficient of variation of the daily lows has median 0.20 (p10 0.11, p90 0.34; data-reliability
  found 0.24 on its 12 longest series), and the cheapest day of a month is typically 22 % below the
  month's median (min/median median 0.78, p10 0.66). So on a mature route a −30 % day is roughly a
  one-in-ten day, not an anomaly. The stricter maturity gate (data-reliability item 2) removes the
  small-sample bias; it does not change this: once months are mature, the −30 % and 15 € rule
  (D24) will still flag "good days" unless a second condition is added (section 3).

Two more patterns, measured as price divided by the route-month median:

| Lead time (found → departure) | < 7 d | 7–13 d | 14–29 d | 30–59 d | 60+ d |
|---|---|---|---|---|---|
| Median price ratio | 1.14 | 1.00 | 1.00 | 0.94 | 1.03 |

| Departure weekday | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| Median price ratio | 1.01 | 0.98 | 0.99 | 1.00 | 1.02 | 0.94 | 1.10 |

Small samples (eleven days of history), but the directions match what travellers expect: last
week departures cost more, Saturday departures less, Sunday departures more.

---

## 2. Part A: price-data sources

Each option: what it gives, terms, cost, limits, coverage from Portugal, traceability (a real,
dated, linkable price?), integration effort behind `collector/`, verdict. "Checked" dates are
when the page was read. Pages behind a login or rendered only by JavaScript are named as such.

### A1. Aviasales GraphQL Flights Data API (Travelpayouts) — **recommended, for enrichment**

- **What:** `POST https://api.travelpayouts.com/graphql/v1/query`, header `X-Access-Token`
  (the token we already have). Queries `prices_round_trip`, `prices_one_way`,
  `special_offers_round_trip`, `special_offers_one_way`, `weekend_prices_round_trip`. Introspected
  on 2026-10-15 (schema from the server, see appendix).
- **Access:** "Access to GraphQL is open to all partners signed up for Travelpayouts and connected
  to the Aviasales program." (support article 4417975783314, checked 2026-10-15). Same cache as
  the REST Data API ("prices from the cache based on the user's search history", stored 7 days:
  article 203956163).
- **Rate limit:** 60 requests/minute (article 4402565416594, table row `/graphql/v1/`), confirmed
  by the `X-Rate-Limit: 60` header on every probe. `prices_for_dates` has 600/min.
- **Parameters that matter for us** (`ParamsRoundTrip`): `origin`, `destination` (airport, city or
  country), `depart_months` **as a list** (several months in one request), `depart_dates`,
  `return_dates`, `depart_date_min/max`, `return_date_min/max`, `trip_duration_min/max` (nights),
  `direct`, `convenient` (≤ 1 stop, no overnight or ≥ 4 h layovers), `with_baggage`, `value_min/max`;
  `grouping` NONE | DEPART_DATE | DATES | DATES_NUM_OF_CHANGES | DIRECTIONS | YEAR_MONTH; `paging`
  limit/offset; `currency`, `market`.
- **Fields we do not get today** (`Price` type): `found_at` (Unix time, exact, versus the
  `search_date` day we parse from the link), `with_baggage` and `baggage_code` ("0PC" = no checked
  bag), `gate` (the agency selling it), `main_airline`, `segments`, `duration`, `convenient`,
  `no_night_change`, `discount` ("deviation from average price for current ticket", Aviasales' own
  measure), `provider`, `ticket_link` (the same `/LIS1011PAR12111?t=…&search_date=…` path the REST
  link carries, minus the `/search/` prefix: convertible by the partner-links API exactly like today).
- **Coverage, probed:** Lisbon–Paris Nov 2026 nonstop 2–10 nights: 466 rows, 36 trips, found on
  8 days; 65 of the first 300 rows `with_baggage: true`. Porto to
  anywhere, Nov 2026, nonstop, grouped by direction: 51 destinations with a cached price. Thin
  routes (FNC–MAN, FAO–DUB, PDL–BOS): 0 rows, exactly like the REST endpoint. Months 2027-03/04/06
  for Lisbon–Paris: prices present (so the horizon is not the limit; demand is).
- **Traceable:** yes: price, currency, found time, airline, dates, a link to the same search. One
  caveat for the "same place as the link" rule (D13): the GraphQL `value` for a trip is the agency's
  price (several rows per trip); the deep link opens the search, as today.
- **Terms:** the Data API's (content pages, caching encouraged: "it is recommended that you use
  them to generate static pages"; "We strongly recommend that you use cached data"); affiliate
  programme rules unchanged (D12).
- **Cost:** 0 €.
- **Effort:** M. Do **not** replace the bulk collector with it: at 60/min, 360 routes × 1 query
  (three months per query) is 6 minutes per run, 12 runs a day, about 2 200 Actions minutes a month
  against the 2 000 free (D23's budget). Use it for the few offers that matter: each run's low
  prices and candidates (tens, not thousands): one query per (route, departure date, return date),
  match on airline and price, store `with_baggage`, `baggage_code`, `gate`, `found_at` on the
  observation (schema bump), archive the answer with the run. Then captions and pages can say
  "só bagagem de mão" or "com mala de porão incluída", which is what deferias prints on every deal
  and what a traveller checks first.
- **Verdict:** the best cheap win on the data side. Ticket T1.

### A2. Other Aviasales Data API endpoints (REST) — see data-reliability, plus three not covered there

Data-reliability §1 tested `grouped_prices`, `get_latest_prices`, `month-matrix`, `week-matrix`,
`calendar`, `cheap` and `latest` and concluded "don't add any other Data API endpoint" (same cache;
`month-matrix` even returns untraceable midnight points). Our one `grouped_prices` probe agrees
(20 departure days for LIS–PAR Nov, a subset of `prices_for_dates`). Three endpoints that report
did not look at (same token and cache, article 203956163; limits article 4402565416594):

| Endpoint | Gives | Limit/min | Use for us |
|---|---|---|---|
| `/aviasales/v3/get_special_offers` (REST) and GraphQL `special_offers_round_trip` | "abnormally low prices for air tickets to selected destinations", with Aviasales' `discount` | 600 / 60 | probed: 23 offers from Lisbon on 2026-10-15 (e.g. Praia 107 € "−65 %", Rome 93 € "−50 %", Alicante 121 € "−46 %" by Aviasales' own average). A free second opinion for the review page: "o Aviasales também o considera uma oferta especial (−50 % vs. a média deles)". Never displayed as a price: their average is not traceable |
| `/aviasales/v3/search_by_price_range` (`value_min/max`, `direct`) | tickets within a price band, destination `-` for all | 600 | an "anywhere under X €" source; our explorer already answers this from stored data, which is better (dated, traced) |
| `/aviasales/v3/get_popular_directions` (`destination`) | from which origins a destination is most searched | 600 | a demand signal in the other direction; Eurostat is better (A12) |

**Markets (probed, negative):** the article says the cache is per market and defaults to the
origin's market. We queried six thin and thick routes with `market` pt, gb, ie, us, de, fr, es,
ch and ru: identical counts and prices in every market (0 for FNC–MAN, FAO–DUB and PDL–BOS; 1 for
FAO–LON; 6 for OPO–GVA). The reverse direction in the foreign market (DUB–FAO, `ie`) has 5
offers while FAO–DUB has 0: British and Irish travellers search their outbound trip, not ours.
A reverse trip is a different product for a Portuguese traveller, so this is not a lever. The
`market` parameter is not a way to see more.

### A3. Aviasales Flight Search API (real-time) — no

"Access to the Flight Search API is only available to projects with at least 50,000 monthly
active users (MAU)" and "we do not make exceptions" (article 210995808, checked 2026-10-15).
Its usage rules (article 34788165535250) also forbid exactly what a collector would do: "It is
prohibited to: automatically collect or scrape data from search results via the API", searches
must be user-initiated, results shown in full with a Book button, conversion ≥ 9 % to Book and
≥ 5 % to purchase, result pages `Disallow`ed in robots.txt. The old version stops on 2026-06-15
(already past); the new one has the same gate. Not a data source for us, by design.

### A4. Kiwi.com — no

- Through Travelpayouts: "To access the API, your Project must have at least 50,000 MAU. We don't
  provide access to Projects with fewer MAU." (article 360019237899, checked 2026-10-15).
- Directly: `partners.kiwi.com` redirects to a Kiwi.com article of 2024-05-30 saying the public
  affiliate programme, API and white label are closed and "any new partnerships on the Tequila
  platform will be on an invitation only basis". `tequila.kiwi.com` is a JavaScript app with no
  public sign-up text.
- Note: Kiwi.com appears as a selling agency (`gate`) inside the Aviasales cache, so its fares
  reach us anyway through the partner's search.

### A5. Travelpayouts partner brands with data feeds — nothing for flights beyond Aviasales

Article 20384016664594 (checked 2026-10-15) lists every brand that gives partners an API or feed:
flights = Aviasales (Data API, no approval; Search API, approval) and Kiwi.com (approval, A4);
Omio (a feed of popular destinations, trains and buses: not our scope); GetTransfer; Airalo (a
feed of eSIM prices per country: we use Yesim, D37, so only relevant if the programme changes);
Tiqets (a feed of cities and offer ids for widgets: could pick a city page for the activities
block instead of the brand home, D37's open `destinations` item); WeGoTrip; Viator (a feed of
discounted tours). No other flight brand (WayAway, Trip.com, Expedia, Booking.com flights) offers
data. The programme directory itself is behind the dashboard login (not re-read; D12 covers the
Aviasales rules: content channels allowed, PPC forbidden, links only from the network's tools).

### A6. Skyscanner — no for data; affiliate later

- **Travel API:** "If you're an established business with a large audience, you can apply"
  (partners.skyscanner.net/product/travel-api, checked 2026-10-15); reviewed by hand within two
  weeks; and the decisive sentence in its FAQ: "we can only offer you our API if the searches
  result in end user bookings", because Skyscanner may distribute partners' pricing data only "for
  the purpose of generating bookings for them". Price-only use is pointed to a Data Products team
  and a GDS. The Indicative Prices API would be the fit ("the cheapest prices seen last by our
  travellers", "cached and can be up to 4 days old", grouped by day or month: cheaper and shallower
  than Aviasales' cache for us), but its guidelines also require "Powered by" Skyscanner branding
  and deep links through Skyscanner. Our links must come from Travelpayouts, so even with access
  the price would not come from the same place as the link (D13).
- **Affiliate programme (Impact):** open to "Travel websites", "Blogs", "Deals websites" with "The
  website's traffic volume is higher than 5,000 unique visitors per month" and HTTPS, up-to-date
  travel content; "Widgets are available to use without signing up to the programme, but no
  commission will be earned". It gives links, widgets and banners, not data. Keep D13's "revisit
  once the website has traffic"; it would be a second link source, which the constraints do not
  allow today, so it stays a note.

### A7. Duffel — no

Checked 2026-10-15: `duffel.com/pricing` and the Services Agreement (last updated 2026-06-17).
There is no per-search fee as such: searches are free up to a 1 500 : 1 search-to-order ratio and
0.005 USD per excess search; with zero orders "zero Orders shall be treated as one Order", so 1 500
free searches a month, then 0.005 USD each (10 000 searches ≈ 42.50 USD), and clause 9.2(b) lets
Duffel suspend an account that stays above the ratio. The terms, not the price, rule it out:
clause 2.5 forbids to "republish, download, display, transmit, or distribute all or any portion
of the Services", to "access or use the Services for metasearch purposes (including … to
redistribute to a metasearch platform)" and (k) any "marketing activities … in respect of … the
Supplier or Supplier Data" without the airline's written consent; fares are "Supplier Data".
Also: Ryanair and Wizz Air are not on Duffel's airline list (easyJet, TAP, Vueling, Transavia,
Azores Airlines, Iberia are), and FR plus W4/W6 are 43 % of our observations. D1's reading stands.

### A8. Amadeus Self-Service — gone

developers.amadeus.com (read in the browser 2026-10-15): "Amadeus for Developers self-service
portal has been decommissioned on July 17th, this website is for Amadeus Enterprise API Portal
only". Enterprise access is by request, consultant-led, no published price. Flight Price Analysis
(the min/quartiles/median endpoint) went with it. Nothing to do.

### A9. Google Flights — nothing official

`developers.google.com/travel` is a 404; `developers.google.com/hotels` lists hotel feeds only
(partners sending prices to Google). Google Flights help pages describe consumer price tracking and
"price insights" e-mails, no API or export. Google's Terms (effective 2026-07-30) forbid "using
automated means to access content from any of our services in violation of the machine-readable
instructions on our web pages" and list "scraping content that doesn't belong to you" as grounds
for suspension. Third-party "Google Flights API" actors exist on scraping marketplaces; they are
scraping, so D13 excludes them.

### A10. Airlines (Ryanair, easyJet, TAP, Vueling, Wizz Air, Transavia, SATA) — no feeds

No airline site read on 2026-10-15 offers a public fare feed or API; TAP's partner pages are
loyalty partners; easyJet's site blocked the fetch, Ryanair's and Vueling's terms pages are
JavaScript apps (Ryanair's rendered no readable text, so its anti-scraping clause is not quoted
here; D13 records the litigation history). Ryanair, Wizz Air and TAP do run affiliate programmes
through other networks (Awin and similar: checked only through D13's earlier notes, not re-read),
which would be a second link source and are therefore out. Scraping is out by rule.

### A11. KAYAK Affiliate Network — no

`developers.kayak.com/flights-price-insights-api` (checked 2026-10-15): "Retrieve cheapest prices
seen last by our travellers", per route or per calendar day/month, with deeplinks that "contain
some tracking information" and a note that user-agent misuse "may impact invoicing". Access by
"Get in touch" through affiliates.kayak.com; no public terms, cost or caching rule. It covers
Europe (its examples are London–Faro in EUR). It is a competing affiliate network whose price
would have to be shown with its own tracked link, which the constraints exclude. Not pursued.

### A12. Eurostat `avia_par_pt` — **recommended, for demand (not prices)**

- **What:** "Air passenger transport routes between partner airports and main airports in
  Portugal": passengers carried, passengers on board, seats and flights per **airport pair**,
  monthly, quarterly and annual, from 2003. Compiled by INE from ANA and ANAC data (Eurostat
  metadata `avia_pa_esms` and `avia_pa_esms_pt`, checked 2026-10-15).
- **Probed through the public API** (JSON-stat, no key):
  `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/avia_par_pt?format=JSON&lang=EN&unit=PAS&tra_meas=PAS_CRD&freq=M&sinceTimePeriod=2024-06`
  returned 513 pair codes, 277 with values for 2024-06 … 2024-12, dataset last updated
  2025-10-22; the latest monthly period is **December 2024** (the monthly series lags about a
  year; annual 2024 is there too). December 2024, passengers carried: Lisbon–Madrid 141 591,
  Lisbon–Paris-Orly 113 321, Lisbon–Madeira 105 331, Lisbon–Barcelona 101 741, Porto–Orly 94 280,
  Lisbon–Heathrow 80 217, Lisbon–São Paulo 79 051, Porto–Madrid 76 787, Lisbon–Amsterdam 69 452,
  Porto–Geneva 63 140, Lisbon–Rome 56 925. Pairs with data that month: Lisbon 103, Porto 54, Faro
  50, Madeira 44. Small routes are suppressed for confidentiality ("only routes above a certain
  threshold are disseminated").
- **Licence:** Eurostat's copyright notice (ec.europa.eu/eurostat/help/copyright-notice):
  "Reuse of statistical data … for commercial or non-commercial purposes is authorised provided
  the source is acknowledged"; editorial content CC BY 4.0; modifications must be stated.
- **Cost:** 0 €. **Limits:** none stated for this API; one download a month is all we need.
- **Use:** a `demand` figure per route (last twelve available months, by departure month for
  seasonality) stored on `routes` at discovery time; order origin and destination pages and
  explorer ties by it; pick which routes get the daily months 4–6 pass (A17); say on a thin route's page
  "rota pouco procurada: os preços aparecem raramente" with the Eurostat month as context (a
  passenger count is not a price, so the traceability test is untouched); keep a dormant-but-busy
  route active a little longer. Attribution line on the About page. Ticket T3.
- **Why not INE directly:** INE's API is free (CC BY 4.0, "Source: Instituto Nacional de
  Estatística – Portugal") and fresher (monthly flash about 45 days after the month, e.g. August
  2026 on 2026-10-14) but it publishes airport totals by country or continent, **not airport
  pairs**. Good for a "Faro recebe X passageiros em agosto" fact, not for ranking routes.

### A13. ANAC and ANA — no reuse

ANAC publishes monthly PDF "Monitorização Mensal do Tráfego Aéreo" (latest August 2026) and
quarterly bulletins, but its terms say contents cannot be used outside the portal without written
consent and "não podendo ser alterada ou explorada comercialmente". ANA's site terms allow
personal, non-commercial use only and forbid reproduction; its destinations pages are JavaScript
apps with no data download. Both are fine to read by hand when writing a destination page; not
sources.

### A14. AeroDataBox — optional, for schedules only

Flight schedules and "airport daily routes & frequencies" (no prices), Portugal coverage 99 %
(their table, 2026-06-03). Paid plans from 7.50–8 USD/month on API marketplaces allow commercial
display; the free tier forbids commercial use; data may be stored for 7 days on small plans
("you may only store our data for 7 days"), longer on 75+ USD plans; derived statistics may be
kept. Terms updated 2026-10-11. Useful only if we want "quem voa: Ryanair 4×/semana" on route
pages or to detect seasonal routes before the cache does. Not needed for prices; parked.

### A15. OpenSky Network — no

"for research and non-commerical purposes", "the API does not provide commmercial flight data such
as airport schedules"; commercial use by contact. Previous-day ADS-B arrivals/departures per ICAO
airport only. Not usable.

### A16. School and public-holiday data (for the site, section 4)

Portuguese public holidays are already data (D31). School holidays: the calendar for 2024/25 to
2027/28 is Despacho n.º 8368/2024 (Diário da República), with a 2026 amendment moving the start of
secondary science-humanities courses to 2026-09-21 reported by several outlets (Despacho n.º
10430/2026, not read in the DRE during this research: to verify when the ticket is done).
Reported 2026/27 breaks: Christmas 2026-12-16 … 12-31 (one source says 12-18), Carnival
2027-02-08 … 02-10, Easter 2027-03-22 … 04-02, end of classes 2027-06-04 / 06-11 / 06-30 by
year group. Madeira and the Azores have their own regional calendars (Madeira's is a regional
despacho PDF). All official, public, reusable as facts.

### A17. `months_ahead` and cadence — see data-reliability §2 and §4; two additions

That report recommends months 4–6 once a day (far months are thin: 2–10 offers per route-month)
and a reliable 2-hour trigger. Two things to add from this research:

- **Which routes deserve the daily far-month pass.** The GraphQL probe found cached prices for
  Lisbon–Paris in March, April and June 2027; thin routes have nothing at any horizon. Rather than
  all 360 routes (+1 080 requests a day), run the daily pass for the routes with real demand
  (Eurostat rank, A12/T3: the top ~80–120 routes cover the pairs a traveller searches for Christmas,
  Carnaval and Easter) and skip the 121 never-seen ones, which data-reliability item 7 already
  proposes to poll once a day.
- **Persistence as a signal.** 209 observations were seen in one run, 3 490 in five or more: the
  cache keeps prices for days, so `seen_count` is a cheap confidence input (a price seen in ten
  consecutive runs is bookable; one seen once at 03:00 may have been a glitch). Section 3 uses it.

---

## 3. Part A, second half: better baselines with the data we have

Data-reliability §3 fixes the day-count side: ≥ 10 daily lows over ≥ 9 days with ≥ 2 departure
dates per day for promotions, ≥ 7 days for low prices, and the baseline (days, span, min–max)
shown to the reviewer. Take that as the base. The points below are what remains once a baseline
is mature. All of it is detector work (pure functions, `now` passed in, D3/D24 unchanged in
spirit) and testable offline on the archive. None of it shows an estimated price on a page:
estimates change whether something is flagged, the page still shows the observation and the
recomputed typical low.

1. **Confidence as words, on the site and in the texts, not only in the queue.** Inputs we have:
   baseline days, span, dispersion of the daily lows (CV), distinct departure dates, and the
   candidate's `seen_count`. Three levels: *low* (below the data-reliability gate), *medium*,
   *high* (≥ 14 days, CV ≤ 0.25). Route pages print it next to the typical low ("histórico de 3
   semanas"), the WhatsApp text and captions say "−x % face ao habitual" only at medium or high
   (otherwise "o preço mais baixo que vimos nesta rota"). Travellers see the claim's strength;
   deferias gives them none.
2. **"New low" on top of −30 %, for mature months.** Because a −30 % day is a one-in-ten day on
   mature routes (section 1), require a promotion candidate to also be below the **minimum daily
   low of the lookback window** (minus a small margin, say 5 %), i.e. cheaper than anything seen for
   that route-month in 90 days. Data-reliability's replay tried "price below every baseline day"
   alone on 4–6-day baselines and found it filtered the wrong ones; on ≥ 10-day baselines the
   minimum is a real floor, which is why it belongs after the maturity gate, not instead of it.
   A low price keeps the −15 % rule. This is what "promoção" means to a reader of deferias: a
   price they have not seen before, not a cheap Tuesday.
3. **Lead-time-aware comparison.** The baseline mixes fares found 60 days out with fares found
   5 days out, and the latter are ~14 % dearer. Keep one typical low per month (D3) but compute it
   from daily lows of offers with lead time ≥ 7 days; evaluate last-minute candidates (< 7 days)
   against it with the same threshold. Cheap to add, removes a bias that will otherwise flag
   nothing in the last week and too much two months out.
4. **Weekday awareness, only for the explorer and copy.** Saturday departures run 6 % below the
   month median, Sunday 10 % above. Not enough history to put this in the baseline; use it as a
   sentence on route pages once a route has ≥ 30 days ("partidas ao sábado costumam ser mais
   baratas"), computed from traced observations, no price string.
5. **Seasonal fallback (estimate, detection only).** For a route-month with 1–3 days, borrow the
   ratio between months from the same route's history once it has two mature months, or from the
   kind (europe/domestic) average; use it only to decide `insufficient_history` versus "evaluate
   with low confidence", never as a number on a page. Worth adding only after the backtest shows
   the gain; listed here because the issue asked.
6. **Aviasales' own signals as a cross-check (A2):** `special_offers` membership and the GraphQL
   `discount` for the candidate. Shown in the review queue as "o parceiro também o marca como
   oferta especial (−50 % vs. a média deles)". A disagreement (we flag, they do not) is a prompt to
   look, not a rule.
7. **A committed backtest harness.** Data-reliability replayed runs 19–57 by hand ("scripts were
   in the session scratchpad") and asks for a rerun at 30+ days. `detector.py` is pure and the
   archive holds every payload (D18): make the replay a script in the repo that takes rule sets and
   reports, per set, candidates per day, how many later expired within 24 h (a proxy for "not
   really bookable"), and how many were new lows. Thresholds then stay measured choices as the
   history grows. First step of ticket T2.

Lastly, the 121 routes without any price: they are mostly seasonal UK, Irish and German routes
from Faro and Madeira, Azores inter-island and Porto's long-haul (D23). No source above fills
them. The right behaviour is already in place (dormancy); the Eurostat demand figure lets the
route page say why ("rota sazonal", "rota pouco procurada") instead of looking broken.

---

## 4. Part B: the site, measured against deferias.pt

Read on 2026-10-15 as a visitor (home, a promotion page, the "de Lisboa" listing, the guides
index, the rules page, "Sobre nós", the account login page). Not scraped, no deal reused, no text
copied. deferias.pt is run by kamaviNET sp. z o.o. (Warsaw), the team behind Fly4free, and covers
flights, hotels, packages, cars and cruises from Portugal.

### What they do well (and whether to adopt)

| deferias.pt | Adopt? | How, within our rules |
|---|---|---|
| Headline per deal "Voos diretos de Lisboa para BUDAPESTE desde €77", with **baggage** ("c/ mala de porão" or "um item debaixo do assento"), the airline, "Melhores preços em Janeiro", and "Rotas: Lisboa – Budapeste – Lisboa" | Yes | We already name the arrival airport and dates (D10/D11). Add the baggage line from GraphQL (A1, T1) and the "melhores meses" we already compute on hubs |
| Top navigation by origin: do Porto, de Lisboa, de Faro, da Madeira, dos Açores | Yes | We have `/partidas/<origem>/` (D30); surface them as chips in the header and on the home, and let the home list filter by origin without JavaScript (one page per origin already exists) |
| "Disponibilidade: Melhores preços em Janeiro", then a link to the airline's week view | Partly | Our calendar on route pages is better (every day is a traced observation); link the promotion to its route page's calendar |
| A reminder that prices were correct at publication and can change | Yes, we do more | We print found and verified times, expire promotions and keep them noindex without a button (D35); say it in one plain sentence on the promotion page as they do |
| Guides: ~100 destination guides, airline guides (Vueling, TAP, Transavia, Ryanair, Wizz Air, Lufthansa, easyJet, "viajar com crianças na…"), practical lists | Yes, slowly | Our tips collection (D33) has 6 tips and 5 itineraries. Airline guides are the obvious next batch: pt-PT search traffic for "bagagem Ryanair" is perennial, facts are on the airlines' own pages, and they feed the baggage line. Human review stays mandatory |
| Alerts and newsletter through an account (conta.deferias.pt), plus Telegram and WhatsApp channels, Instagram, Facebook | Yes, without accounts | We have no account system and no cookies, and should keep it that way. Per-origin Telegram channels or a bot (free, no cookies), a weekly e-mail digest through a privacy-first provider (Buttondown: free for the first 100 subscribers, tracking off by default, custom domain), and a WhatsApp Channel posted by hand with the text the review page already gives (D32). T5 |
| "Parcerias & Descontos" page and in-deal blocks: insurance (Heymondo), eSIM (Airalo, Holafly), Revolut, car hire, flight-compensation claims, group trips | Partly | A `/parcerias/` page listing Yesim and Tiqets with the affiliate disclosure costs little and answers "which eSIM?" from search. Insurance waits for a programme for Portuguese residents (D37). Compensation claims: check whether a programme exists on Travelpayouts before adding a block (Miguel, dashboard). Revolut-style referral codes are personal links, not Travelpayouts: out |
| "Paga-nos um café" donation button | Yes, trivial | An outbound link to a donation page (Ko-fi or similar); no script on our site |
| Cookie banner with 210 ad partners, programmatic ads | No | Our selling point: no cookies, no banner, no ads (spec: revisit ads at > 10k visits/month) |
| "Add as a source in Google" nudge | Maybe | Google's preferred-sources feature; a link in the footer, no script |
| News posts (TAP privatisation, Readers' Choice) | No | Spec out of scope; our edge is data, not news |

### Where we are, or can be, better than them

- **Traceable prices.** Every price on our pages links to the observation it came from, with
  found and verified times, and the test suite refuses any other price (D24). deferias prints a
  price and a date of publication. Say this on the home page in one line; it is the reason to trust
  a promotion.
- **A real "preço habitual".** Our typical low is computed from stored daily lows per route and
  month; theirs is editorial. With recommendation 1 the "−x % face ao habitual" becomes a measured,
  confidence-labelled claim; print the confidence as words ("histórico de 3 semanas").
- **Explorer and pontes (D31).** They have no "para onde posso ir por menos de X €" and no
  long-weekend planner. Add school holidays (T4) and keep the explorer as the home of every
  "where can I go" question; link it from every promotion and origin page.
- **Route pages with calendars and best months (D30):** deferias has nothing per route; these
  pages are our SEO base ("voos baratos Lisboa Budapeste"). Add the demand-based ordering (T3)
  and the baggage line (T1).
- **No account needed** for alerts (T5), and no cookies.

### Site ideas, ranked by value for the traveller against effort (with the data each needs)

| # | Idea | Value | Effort | Data needed |
|---|---|---|---|---|
| B1 | Baggage line on promotions, low prices and captions ("só mala de mão" / "com mala de porão") | High | M | GraphQL enrichment (T1), schema field, caption and page templates, traceability unchanged (no new price) |
| B2 | Low-price alerts: daily per-origin Telegram digests (the run's low prices, found date, partner link, disclosure); a weekly e-mail digest | High | M | low prices already computed every run (D24); `partner_links`; Buttondown API key (Miguel) |
| B3 | School-holiday planner next to pontes: `/ferias-escolares/<slug>/`, explorer filter "férias escolares", mainland/Madeira/Azores calendars | High for families | M | Despacho 8368/2024 dates as YAML (A16); pure window rule like `pontes.py` |
| B4 | Origin chips on the home and header; home list filtered per origin page | Medium | S | nothing new (origin pages exist) |
| B5 | Route demand ordering and "rota pouco procurada" notes | Medium | S | Eurostat (T3) |
| B6 | Airline guides as tips (bagagem, tarifas, check-in, crianças) for Ryanair, easyJet, TAP, Vueling, Wizz Air, Transavia, SATA | Medium (SEO) | S each, review by Miguel | airlines' official pages as sources, `last_checked` |
| B7 | `/parcerias/` page (Yesim, Tiqets, insurance when available) with the block disclosure | Medium | S | config `affiliate.programmes` (D37) |
| B8 | "Quando reservar" sentence on route pages from lead-time ratios (no price strings) | Medium | S after T2 | ≥ 30 days of history per route |
| B9 | Promotion page: "o parceiro também marca esta oferta como especial" badge | Low-medium | S | `special_offers` (A2), review snapshot field |
| B10 | Donation link, "add as a source in Google" footer link, Search Console submission (checklist step still open) | Low | S | none |
| B11 | WhatsApp Channel (manual posting of the existing text) | Medium | 0 code | Miguel creates the channel; D32's text |
| B12 | Hotels and car hire blocks on itineraries (Hotellook and the car programmes on Travelpayouts have widgets and feeds) | Medium (revenue) | M | spec says hotels are v3: a config-only programme like D37 when wanted |

Monetisation beyond flights that fits the rules: eSIM and activities blocks exist (D37); next are
insurance (when a programme serves Portuguese residents), hotels through Hotellook (Travelpayouts,
widgets and API without approval per A5's article) on itineraries, and car hire on island
itineraries. All through Travelpayouts links, all with the block disclosure, no cookies before a
click.

---

## 5. Constraint check per recommendation

| Rec. | No scraping | No fabricated price | Links only via Travelpayouts API | No cookies, scripts on click only | Low cost |
|---|---|---|---|---|---|
| 0 Data-reliability items | same API, same token | same observations, stricter gate | unchanged | n/a | 0 € |
| 1 GraphQL enrichment | an API we are licensed for, same token | baggage and agency are fields of the same observation; no new price string | `ticket_link` converted by the partner-links API, as today | n/a | 0 €, tens of requests per run at 60/min |
| 2 Backtest and rules | pure code on stored data | changes only what is flagged; pages show observations; confidence is words, not a number | n/a | n/a | 0 € |
| 3 Eurostat demand | public statistics API, reuse with attribution | passenger counts, not prices; attribution on About | n/a | fetched by the pipeline, nothing on the client | 0 € |
| 4 School holidays | official calendar as data | no prices in content (pt-PT lint) | n/a | static pages | 0 € |
| 5 Alerts | n/a | digests reuse traced low prices with found dates and the disclosure | stored `partner_links` only | Telegram and e-mail are off-site; the subscribe form is a plain POST to the provider, no script; say so on the privacy page | 0 € to 100 subscribers, Telegram free |
| 6 special offers cross-check | same API | review-only signal, never a page | n/a | n/a | 0 € |
| 7 Small site wins | n/a | no new prices | partnerships page links via `article_links`-style stored links | donation and Google links are plain `<a>` | 0 € |

---

## 6. Sources (all read 2026-10-15 unless noted)

Travelpayouts / Aviasales
- Requirements for Aviasales data API access: https://support.travelpayouts.com/hc/en-us/articles/203956083
- Aviasales Data API (endpoints, markets, 7-day cache): https://support.travelpayouts.com/hc/en-us/articles/203956163
- API rate limits (table, 2024-06-14): https://support.travelpayouts.com/hc/en-us/articles/4402565416594
- Aviasales GraphQL for access to Flights Data API: https://support.travelpayouts.com/hc/en-us/articles/4417975783314 (schema introspected at https://api.travelpayouts.com/graphql/v1/query)
- Brands that provide access to APIs and data feeds: https://support.travelpayouts.com/hc/en-us/articles/20384016664594
- How to get access to the Aviasales Search API (50 000 MAU): https://support.travelpayouts.com/hc/en-us/articles/210995808
- Search API usage rules: https://support.travelpayouts.com/hc/en-us/articles/34788165535250
- Kiwi.com affiliate program API (50 000 MAU): https://support.travelpayouts.com/hc/en-us/articles/360019237899
- Flight data by Aviasales (static JSON files): https://support.travelpayouts.com/hc/en-us/articles/360018907280
- Older Data Access API docs (2017, v1/v2 only): https://travelpayouts-data-api.readthedocs.io/
- Aviasales programme rules: dashboard, login-gated; as recorded in DECISIONS D12 (2026-10-12)

Other providers
- Skyscanner Travel API: https://www.partners.skyscanner.net/product/travel-api ; FAQ: https://developers.skyscanner.net/docs/faqs ; Indicative Prices: https://developers.skyscanner.net/docs/flights-indicative-prices/overview ; usage guidelines: https://developers.skyscanner.net/docs/getting-started/usage-guidelines ; rate limits: https://developers.skyscanner.net/docs/getting-started/rate-limits ; affiliates: https://www.partners.skyscanner.net/product/affiliates
- Kiwi.com partnerships (2024-05-30): https://media.kiwi.com/articles-and-interviews/better-for-business-kiwi-com-takes-a-new-approach-to-partnerships/
- Duffel pricing: https://duffel.com/pricing ; Services Agreement (2026-06-17): https://duffel.com/services-agreement ; airlines: https://duffel.com/airlines
- Amadeus for Developers (decommission notice): https://developers.amadeus.com/
- Google: https://developers.google.com/hotels ; https://support.google.com/travel/answer/6235879 ; https://support.google.com/travel/answer/7664728 ; https://policies.google.com/terms
- KAYAK Flights Price Insights API: https://developers.kayak.com/flights-price-insights-api
- AeroDataBox: https://aerodatabox.com/pricing ; https://aerodatabox.com/terms ; coverage: https://aerodatabox.com/data-coverage
- OpenSky REST API: https://openskynetwork.github.io/opensky-api/rest.html

Public data
- Eurostat `avia_par_pt` metadata: https://ec.europa.eu/eurostat/cache/metadata/en/avia_pa_esms.htm and https://ec.europa.eu/eurostat/cache/metadata/EN/avia_pa_esms_pt.htm ; API call used: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/avia_par_pt?format=JSON&lang=EN&unit=PAS&tra_meas=PAS_CRD&freq=M&sinceTimePeriod=2024-06 ; copyright notice: https://ec.europa.eu/eurostat/help/copyright-notice
- INE terms (CC BY 4.0): https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_cont_inst&INST=3585857 ; API: https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_api_v2 ; August 2026 flash: https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_destaques&DESTAQUESdest_boui=707270835&DESTAQUESmodo=2
- ANAC newsletters: https://www.anac.pt/vPT/Generico/PublicacoesINAC/newslettersdetrafego/Paginas/NewslettersdeTrafego.aspx ; terms: https://www.anac.pt/vPT/Footer/Paginas/TermoseCondicoes.aspx ; ANA: https://www.ana.pt/
- School calendar: Despacho n.º 8368/2024, https://diariodarepublica.pt/dr/detalhe/despacho/8368-2024-873447631 ; Madeira 2026/27 calendar PDF on madeira.gov.pt ; the 2026 amendment (Despacho n.º 10430/2026) reported by press, to verify in the DRE

Tools and the reference site
- Buttondown pricing (free for the first 100 subscribers, "Privacy-first"): https://buttondown.com/pricing
- deferias.pt, read as a visitor: https://www.deferias.pt/ , https://www.deferias.pt/ofertas/de-lisboa/ , https://www.deferias.pt/guias/ , https://www.deferias.pt/sobre-nos/ , https://www.deferias.pt/regras-de-utilizacao/ , one promotion page (Lisbon–Budapest), https://conta.deferias.pt/ (login page only; no account created)

---

## 7. Draft tickets (opened on 2026-10-15 as #46 T1, #47 T2, #48 T3, #49 T4, #50 T5)

Format per `docs/agents/issue-tracker.md`. Milestone in the title prefix. Each is ≤ half a day to
two days of agent work; T1 and T2 are the larger ones and could be split.

### T1 — M1 Enrich low prices and candidates with baggage and agency from the Aviasales GraphQL API

**Ações do Miguel:** nenhuma (o token da Travelpayouts já está no `.env` e nos secrets).
Confirmar no fim, numa promoção real, que a linha de bagagem bate certo com o que o Aviasales mostra.

**Goal:** every low price and promotion candidate knows whether a checked bag is included and
which agency sells it, from the same cache the price came from, so captions and pages can print
"só bagagem de mão" / "com mala de porão incluída" and the reviewer sees the seller.

**Scope**
- `collector/graphql.py`: a small client for `POST /graphql/v1/query` (`X-Access-Token`), rate
  limit 60/min (own `RateLimiter`), queries `prices_round_trip` with `depart_dates`, `return_dates`,
  `origin`, `destination`, `direct` from the route rules, `grouping: NONE`, `currency: eur`,
  `market: pt`; archived with the run like REST answers (D18).
- `pipeline.enrich_offers(ctx, conn, offers)`: after detection, for each low price and candidate
  of the run (bounded, e.g. 200 per run), find the GraphQL row with the same airline, dates and
  price (± 0.01 €); store `with_baggage`, `baggage_code`, `gate`, `found_at` on the observation.
  No match → fields stay null, nothing invented.
- Schema v13: four nullable columns on `price_observations`; migration step; `schema.sql`;
  upgrade tested from v5/v7 and a v12 database.
- Captions (`deal.txt.j2`, `whatsapp.txt.j2`), slides (price block) and the site contract
  (`promotions.json`, low prices: additive `baggage` field, `null` when unknown; schema + fixtures
  by hand as in D36) print the line only when known. pt-PT copy in `i18n_pt.py`; web copy in
  `format.ts`.
- Review snapshot and queue page show `gate` and the baggage line.

**Acceptance**
- [ ] A run with GraphQL mocked (respx) enriches only the run's low prices and candidates and
      never changes a price.
- [ ] An offer without a GraphQL match renders no baggage line (no "sem bagagem" guess).
- [ ] Caption, WhatsApp text, promotion page and low-price rows show the baggage line when known;
      `tests/test_traceability.py` and `web/test/traceability.test.ts` still pass (no new price).
- [ ] The 60/min limit is respected under 8 workers; a 429 waits, never fails the run.
- [ ] Contract change is additive in v1; fixtures regenerated or edited by hand with `baggage: null`.

**Verification:** `uv run pytest`, `cd web && npm test`; a dry run on a database copy prints the
enriched fields for that day's low prices.

**Docs to update:** README (collector section), CLAUDE.md (layout line for `collector/graphql.py`
and the rule "baggage only from the GraphQL answer, never guessed"), DECISIONS (D39), GLOSSARY
("bagagem incluída").

### T2 — M1 Backtest the detector on the archive and add confidence, new-low and lead-time rules

**Ações do Miguel:** ler o relatório do backtest e escolher os limiares (o ticket propõe
valores; a decisão é tua).

**Goal:** promotion candidates are measured, not guessed: a committed backtest over the stored
history shows how many candidates each rule set produces and how many expired within a day, and,
on top of the maturity gate from `docs/research/2026-10-15-data-reliability.md` (≥ 10 daily lows,
≥ 9-day span, ≥ 2 departure dates per day; ≥ 7 days for low prices), the chosen rules add a
confidence level, a "new low" condition and lead-time awareness, all pure.

**Scope**
- `scripts/backtest_detector.py` (or `escapadinha detect --backtest`): replay days D-14 … D-1 from
  `price_observations` (and the archive when a day's payloads are needed), running
  `detector.detect` with a rule set per run; report candidates/day, low prices/day, share later
  expired within 24 h, share that were new lows, per kind. Read-only. Reproduces the
  data-reliability replay table as its first fixture.
- `detector.py`: `Baseline` gains `cv`, `min_low`, `lead_days` stats (and the qualifying-day count
  the maturity gate needs, if that ticket has not landed first); `confidence(base, cfg)` →
  `low | medium | high` from days, span and CV (thresholds in `DetectorConfig`); `evaluate` adds
  `require_new_low` (candidate price ≤ `min_low × (1 − new_low_margin)`) and computes the baseline
  from offers with lead time ≥ `baseline_min_lead_days`; `low_prices` require ≥ `low_confidence`.
- Review snapshot, queue page and `deal check` show the confidence and the "novo mínimo" flag;
  WhatsApp text and captions say "−x % face ao habitual" only at medium or high confidence
  (otherwise "o preço mais baixo que vimos nesta rota").
- Config: `detector.confidence`, `require_new_low`, `new_low_margin`, `baseline_min_lead_days`.

**Acceptance**
- [ ] Backtest report committed under `docs/research/` with the rule sets compared.
- [ ] Unit tests for confidence levels, new-low rule, lead-time filter; a −30 % day that is not a
      new low is no candidate; a new low below −30 % is.
- [ ] `detector.py` stays pure (no I/O, no clock).
- [ ] Review snapshot schema change is additive (`contract/review/v1`), both sides' fixtures pass.

**Verification:** `uv run pytest`; `uv run python scripts/backtest_detector.py data/escapadinha.db`
on a copy.

**Docs to update:** DECISIONS (D3/D24 revised), README (detector), GLOSSARY ("confiança do preço
habitual", "novo mínimo"), config.yaml comments.

### T3 — M1 Route demand from Eurostat `avia_par_pt`: ordering, months_ahead, thin-route notes

**Ações do Miguel:** nenhuma. (Se quiseres, confirma a frase de atribuição na página "Como funciona".)

**Goal:** every route has a demand figure (passengers carried per month on the airport pair, from
Eurostat), used to order pages, to choose which routes look six months ahead and to explain thin
routes; a passenger count is never a price.

**Scope**
- `demand.py` (pure): parse the JSON-stat answer into `{(origin_icao, partner_icao, month): pax}`;
  map ICAO ↔ IATA through `data/airports.json`; sum partner airports into our city codes; return
  per route the last 12 available months and their mean.
- `collector/eurostat.py`: one GET of
  `avia_par_pt?format=JSON&unit=PAS&tra_meas=PAS_CRD&freq=M&sinceTimePeriod=<24 months ago>`,
  archived to the object store; run with discovery (monthly), failure logged and skipped.
- Schema v13/v14: `routes.demand_pax_month` (mean), `routes.demand_period` (latest month), and a
  `route_demand` table (route, month, pax) if seasonality is wanted on hubs.
- Use: origin and destination pages order by demand after price; explorer ties; `months_ahead`
  per route = 6 when demand rank ≤ `collector.deep_routes` (80), else 3 (collector reads it per
  route); route page note "Rota com pouca procura: os preços aparecem raramente" when a route has
  no price and demand is below a threshold, "Rota sazonal" when Eurostat shows months at zero.
- Contract: `routes.json` gets `demand` (additive, nullable); About page attribution line
  "Dados de passageiros: Eurostat, avia_par_pt, reutilização autorizada com indicação da fonte".

**Acceptance**
- [ ] Parsing tested on a saved JSON-stat sample; suppressed cells (":") handled.
- [ ] A route without Eurostat data keeps today's behaviour.
- [ ] `months_ahead` per route changes the request count as expected (test on a fake source).
- [ ] No passenger number is rendered where the traceability test would read it as a price (it
      has no "€"; `pt-lint` passes).

**Verification:** `uv run pytest`; `uv run escapadinha routes discover` on a copy prints the
demand summary.

**Docs to update:** README, CLAUDE.md (layout `demand.py`, `collector/eurostat.py`; rule
"months_ahead per route from demand"), DECISIONS (D40), About page copy.

### T4 — M3 School-holiday planner (férias escolares) next to the pontes

**Ações do Miguel:** confirmar as datas no Diário da República (Despacho n.º 8368/2024 e a
alteração de 2026) e nos calendários da Madeira e dos Açores antes de marcar o ficheiro como
revisto; dizer se queres as três redes (continente, Madeira, Açores) ou só o continente para já.

**Goal:** families can see where to go during school breaks: explorer filter "férias escolares"
and pages per break (Natal 2026, Carnaval 2027, Páscoa 2027, Verão 2027), built from low prices
whose departure and return fall inside the break, with the same rules and look as the pontes.

**Scope**
- `content/school-holidays.yaml`: per school year and network (continente, Madeira, Açores) the
  breaks with start, end, source URL and `last_checked`; a `reviewed: true` gate like D33.
- `pontes.py`-style pure module `school_holidays.py`: windows (break ± 1 day for travel), export as
  `school_holidays.json` (additive contract file, `meta.files`).
- Site: `/ferias-escolares/<slug>/` pages (noindex when empty or past, like pontes), explorer
  filter, titles through `format.ts` (no month names elsewhere), breadcrumbs and JSON-LD like
  ponte pages; links from origin pages and from the pontes index.
- Fingerprint: the new JSON joins `run_path.fingerprint` through `site_data`.

**Acceptance**
- [ ] Windows tested (a trip must start and end inside the window; a break that already passed
      shows "já passou").
- [ ] Fixture build has at least one break page with a traced low price; sitemap lists only
      non-empty future pages.
- [ ] pt-PT lint and traceability tests pass; copy has no prices.

**Verification:** `uv run pytest`, `cd web && npm test`, `npm run lhci` on the new page type.

**Docs to update:** README, CLAUDE.md (layout, "school holidays only from the YAML"), DECISIONS
(D41), GLOSSARY ("férias escolares"), privacy/about unchanged.

### T5 — M5 Low-price alerts: per-origin Telegram digests and a weekly e-mail digest

**Ações do Miguel:** criar os canais públicos no Telegram (um por origem: Lisboa, Porto, Faro,
Madeira, Açores) e pôr o bot existente como administrador de cada um; criar a conta no
Buttondown (plano gratuito até 100 subscritores, tracking desligado), gerar a API key e pô-la no
`.env` e nos secrets do Actions; ler a frase nova da página de privacidade.

**Goal:** a traveller can follow the low prices from their airport without an account and without
cookies: a Telegram channel per origin receives one daily digest of that day's new low prices, and
subscribers get one weekly e-mail digest; both reuse the traced low prices, their found dates,
the stored partner links and the disclosure.

**Scope**
- `posting.py`: a `digest` channel kind with one daily slot per origin (Lisbon time), text from a
  new `captions/templates/digest.txt.j2` (headline per low price: destination, arrival airport,
  price, dates, "encontrado a", link, then `DISCLOSURE`); only low prices not sent before (a
  `digest_sent` table or meta key per observation id); nothing sent when there is nothing new.
- `telegram.py`: `sendMessage` (text, no photo) through the existing `BotApi`, channel per origin
  from config `posting.digest_channels: {LIS: "@…", …}` with the same `channel_problem` check;
  at-most-once record in the object store like D38.
- `newsletter.py`: Buttondown API (`POST /v1/emails` with the week's digest, Markdown), secret
  `BUTTONDOWN_API_KEY`; paused without it; one send per week at a slot; send record in the store.
- Site: a `/alertas/` page explaining the channels and the e-mail digest, with the Telegram links
  and a plain HTML form that POSTs to Buttondown's hosted subscribe endpoint (no script, no
  cookie); privacy page sentence about the provider and what it stores; footer link.
- `queue list` shows digest notices; `deal check` unchanged.

**Acceptance**
- [ ] A run with new low prices sends one message per origin with news and none otherwise (respx).
- [ ] A low price is never sent twice; a lost answer is handled like D38 (no automatic resend).
- [ ] Every digest text carries the disclosure and found dates; the traceability test covers the
      digest template (prices only from referenced observations).
- [ ] No script or cookie added to the site; the subscribe form is a plain POST (tested like the
      no-cookies checks of D34).
- [ ] Without the secrets both channels are `Paused`, never a dry-run that settles the send.

**Verification:** `uv run pytest`; `cd web && npm test`; a first real digest on the test channel.

**Docs to update:** README (alerts), CLAUDE.md (posting rules: digests, Buttondown), DECISIONS
(D42), GLOSSARY ("alerta de preços baixos", "resumo semanal"), `docs/runbooks/alertas.md`
(pt-PT, Miguel's steps), privacy page.

---

## Appendix: what was called during this research

All calls read-only, with the token from `.env` (never printed, never committed), on 2026-10-15:

- Travelpayouts GraphQL: 2 introspection queries; 11 `prices_round_trip` queries (Lisbon–Paris
  Nov/Dec 2026 and Mar–Jun 2027, Porto anywhere Nov 2026, FNC–MAN, PDL–BOS, FAO–DUB, OPO–GVA);
  2 `special_offers_round_trip`; 1 `weekend_prices_round_trip` (rejected: its datetime format is
  `YYYY-MM-DD HH:MM`, noted for T1).
- Travelpayouts REST: 2 `prices_for_dates` and 2 `grouped_prices` for Lisbon–Paris Nov 2026;
  57 `prices_for_dates` for the market probe (A2).
- Eurostat: 2 GETs of `avia_par_pt` (JSON-stat), no key.
- Database: `escapadinha store pull` (generation 46), then read-only SQLite queries and
  `detector.month_baselines` through the project's own modules.
- Browser (as a visitor): deferias.pt pages listed in section 6, Travelpayouts support articles,
  developers.amadeus.com, buttondown.com/pricing.
- Fetch agents read the Skyscanner, Kiwi.com, Duffel, Google, INE, ANAC, ANA, AeroDataBox,
  OpenSky and KAYAK pages listed in section 6. Pages that could not be read are named in the text.

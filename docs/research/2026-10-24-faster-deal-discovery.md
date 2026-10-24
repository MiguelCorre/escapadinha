# Finding promotions faster than the competition

*Research, 2026-10-24. Read-only on the database copy `data/escapadinha.db` (generation of
2026-10-20 17:35 UTC, opened `mode=ro`), web searches and two vendor pages read the same day.
No code, config or store changes. Miguel's brief: "find solutions to find flight deals faster
than the competition; paying or asking for a licence is fine, I'll handle that."*

**Outcome (same day, DECISIONS D46):** Miguel decided that nothing goes out on Instagram or
Telegram until he says so (both publishers paused) and that good deals go live on the website by
themselves. Implemented: automatic approval for the site (rules in `review.auto_approve`), 30-minute
runs with a rebuild throttle, the exact found time and Aviasales' special-offer discount on the
review pages, and the deals-site information on promotion pages. Not implemented: Telegram paging
of the reviewer (no Telegram at all for now) and any new price source (sections 2.1–2.5 are his
call).

Builds on [`2026-10-15-data-reliability.md`](2026-10-15-data-reliability.md) and
[`2026-10-15-more-data-and-site-ideas.md`](2026-10-15-more-data-and-site-ideas.md) (sections A1–A14
list every source checked under the free-tier, no-scraping constraints). This report drops those
two constraints where Miguel said so (money, licences) and says plainly which options still break
D13's "no scraping" rule, so he can decide that too.

---

## 0. The headline

**We are structurally slow, and the slowness is not mainly the data source.** Measured on the
copy:

| Where the time goes | Measured | Why |
|---|---|---|
| A traveller finds a fare → it reaches our database | **median 12.5 h, p90 5.4 days** (7 845 observations; the found time is a day unless `found_at` is known, so noon is assumed) | we read a 7-day cache of other people's searches; nobody searches thin routes daily |
| Our cadence | one run every 2 h, about 2 min each | GitHub Actions budget (D23) |
| A candidate → a promotion a traveller can see | **never, so far**: all 13 deals expired unreviewed; 8 of 13 for "preço habitual ainda sem dados suficientes" | the D40 maturity gate (right, per the backtest) plus a human review step with nobody paged |
| Approval → post | next slot (09:00 / 13:00 / 19:00 Lisbon), then the next 2-hourly run | D32 slots and the run cadence |

A competitor like deferias.pt is a person with Google Flights, Skyscanner and the airlines' own
pages open, posting a Telegram message within minutes of seeing a fare. Beating them means (a)
getting **live** prices instead of a cache, (b) looking **more often**, and (c) **shortening our own
pipeline** from detection to post. (c) is free and the biggest gap. (a) costs money or a legal
decision. (b) costs about 7 €/month.

### Ranked recommendations

| # | What | Gain | Cost | Needs | Breaks a rule? |
|---|---|---|---|---|---|
| 1 | **Shorten our own pipeline**: page Miguel on Telegram the minute a candidate appears (with approve/reject buttons), post to Telegram immediately on approval (no slot), run `publish_due` right after the applier, and allow a bounded **auto-approve** for `high` confidence + new low + nonstop + passing live check (an event writer, D26 stays intact) | hours → minutes | 0 € | code (M) | No |
| 2 | **Run every 30 min instead of 2 h**, and the day's pass twice a day | 4× the chance to see a fare within its first hours | ≈ 7 €/month in Actions minutes, or a 5 €/month VPS | config + Worker cron (S) | No |
| 3 | **Use what the cache already tells us about freshness**: GraphQL `found_at` on every candidate (we have it for 19 rows only), `special_offers` as an early-warning list, and treat a fare found < 2 h ago as "hot" in the review page | better triage, same data | 0 € | code (S–M) | No |
| 4 | **Buy live fares from a licensed data vendor**: OAG/Infare (Retailer PPS, Altus: fares collected from airline websites, GDSs and OTAs, including Ryanair and Wizz Air) or Skyscanner Data Products (Live Pricing Services). Quote-based, enterprise contracts | real-time fares for the first time, legally | likely thousands €/year (no rate card; estimates only) | Miguel contacts sales; a new `PriceSource` | No, but D13's "price from the same place as the link" needs a rethink (§3) |
| 5 | **Duffel enterprise agreement** with the airline's written consent for marketing fares (cl. 2.5(k)) | live fares for easyJet, Vueling, TAP, Transavia | 0 € to search below 1 500 searches/order, then 0.005 USD/search; bespoke enterprise pricing | Miguel asks Duffel sales for an Order Form that lifts cl. 2.5(d) | Their standard terms forbid it; only a signed exception makes it legal |
| 6 | **Google Flights through a scraping API** (SerpApi, Apify actors) | the exact tool the competition uses, every airline, live | 0.12–50 USD per 1 000 searches depending on vendor | an account | **Yes: D13.** Google's terms forbid automated access; the vendor carries the scraping, we carry the terms risk |
| 7 | **Airlines' own fare calendars** (Ryanair `farfnd`, Wizz Air, easyJet endpoints the scrapers use) | the cheapest-per-day fares straight from the airline, minutes old | 0 € | nothing | **Yes: D13.** Ryanair sues (Booking.com, US jury 2024); the endpoints are unofficial and break without notice |
| 8 | Skyscanner Travel API, Travelpayouts Search API, Kiwi.com Tequila | live metasearch prices | 0 € | 100 000 MAU / 50 000 MAU ("we do not make exceptions") / invitation | Not available to us at any price today |

**Do 1–3 now** (they are the cheapest and remove most of the delay), **start the conversations in 4 and 5
this week** (they take weeks and Miguel is the only one who can sign), and **decide on 6–7
knowingly**: they work, they are what the competition effectively does by hand, and they are the
only free way to live fares for Ryanair and Wizz Air (43 % of our observations), but they turn
D13 from a rule into a risk we accept.

---

## 1. Where the time goes today (measured)

Database copy: 7 845 observations fetched 2026-10-12 16:12 … 2026-10-20 17:35 UTC, 375 active
routes, 13 deals (all `expired`, none ever reviewed).

**Cache latency.** For every observation: the day a traveller found the fare (`found_date` from the
link; the exact `found_at` exists for 19 rows, D43's enrichment is young) to our first `fetched_at`.
Assuming noon on the found day when only the day is known: p10 0.3 h, **p50 12.5 h, p90 129 h**. Half
of what we store is more than half a day old when we first see it, a tenth is more than five days
old. The source cannot be faster than its users: the cache holds "prices from the cache based on the
user's search history" (Travelpayouts article 203956163), stored 7 days.

**Cadence.** `17 */2 * * *` on the Worker (D41), 2 min per run. Between two runs a fare found right
after one run waits up to 2 h to be seen, then the full path adds build and deploy minutes.

**Our gate.** The 13 deals: 2 died the same evening because the price rose (correct), 3 for a
3-day freshness rule (correct), 8 for an immature baseline (correct per D40 and the backtest, and
the reason there have been no candidates since 2026-10-16: the gate is doing its job while the
baselines grow). None has `reviewed_at`: a human never saw one in time, because nothing tells
Miguel a candidate exists until he opens the review page.

**Posting.** Instagram waits for the next of three slots; Telegram posts "at once" per D32, but
"at once" means the next 2-hourly run's `publish_due`, after an approve event the applier picks up
on that same run at the earliest.

So, today, the best case from a fare appearing on Aviasales to a Telegram post is about 2–4 h
(seen next run, approved by hand within the run gap, posted the run after), the typical case is
never. deferias.pt posts in minutes.

---

## 2. Options for live prices

For each: what, freshness, coverage from Portugal (the airlines we see most: FR 1 534 observations,
U2 494, TP 431, VY 252, W4 166), cost, access, terms, risk, integration behind `collector/`
(`PriceSource.fetch(…, rules=)`).

### 2.1 Licensed fare data: OAG / Infare — the "pay for a licence" answer

- **What:** OAG bought Infare in 2023 ([BusinessWire](https://www.businesswire.com/news/home/20230728180571/en/OAG-Acquires-Infare-and-Receives-New-Investment-from-Vitruvian-Partners)).
  Infare's business is collecting competitor fares at scale for airlines (240 airlines), "delivered
  daily, multiple times a day or live". OAG sells it as [Retailer PPS](https://www.oag.com/retailer-pps)
  (fare benchmarking for OTAs/TMCs: published and private fares, booking-code availability, custom
  alerts) and [Altus Data](https://www.oag.com/altus-data) (historical fares, flight level, weekly,
  "sources include airline websites, GDSs and OTAs", 400 billion rows). In other words: the licensed,
  industrial version of what scrapers do, including the low-cost carriers that are on no GDS.
- **Freshness:** Infare quotes "live" delivery for airline customers; Altus is weekly (history, not
  alerts); Retailer PPS has alerts. The exact refresh for our routes is a sales question.
- **Coverage:** all carriers from Portugal, in principle (they collect from airline sites). To confirm.
- **Cost:** no rate card anywhere; enterprise quote. A third-party API review says per-request fees
  "subject to individual pricing and quota". Expect thousands of euros a year; the Amadeus
  Enterprise estimates floating around (3–10 k setup, 5–20 k/year) are the right order of magnitude
  for this class of vendor and are unverified.
- **Terms:** a data licence. The product is built for pricing intelligence, not for publishing fares
  to the public: whether we may print "LIS–PAR 39 €" from their feed is the first question to ask.
- **Integration:** a second `PriceSource` producing `Observation`s with `source="oag"` (schema
  already allows several sources: `dedup_key` includes `source`); the deal's `deep_link` would
  still come from Travelpayouts (see §3).
- **Verdict:** the one path that gives live Ryanair/Wizz fares with a signed contract. Miguel:
  request a quote for "alerts on fares from LIS/OPO/FAO/FNC/PDL/TER, 375 routes, refresh ≤ 1 h,
  rights to publish the fare with a link to the airline or an OTA", and ask for a pilot price.

### 2.2 Skyscanner Data Products (Live Pricing Services)

- **What:** Skyscanner's B2B unit sells data: the [Data Products Terms and Conditions](https://www.skyscanner.net/media/data-products-terms-and-conditions)
  define "Travel Insight Services, Travel Insight Vision, Travel Rankings Services, and Live Pricing
  Services" (the page is a JavaScript shell; the fetch returned no clause text, so the clauses are
  not quoted here; it needs reading in a browser). The 2026-10-15 report found that price-only use
  of the Travel API is "pointed to a Data Products team".
- **Freshness:** "Live Pricing" by name; indicative prices are "up to 4 days old".
- **Coverage:** Skyscanner has every carrier from Portugal including Ryanair and Wizz Air.
- **Cost:** quote-based, no rate card.
- **Terms:** unknown until read; the Travel API guidelines require "Powered by Skyscanner" and
  Skyscanner deep links, which would conflict with our Travelpayouts links (§3).
- **Verdict:** worth one e-mail to the Data Products team in parallel with OAG. Lower odds than OAG:
  their FAQ says they distribute pricing data "for the purpose of generating bookings for them".

### 2.3 Duffel (enterprise agreement)

Read 2026-10-24: [pricing](https://duffel.com/pricing), [services agreement](https://duffel.com/services-agreement),
[airlines](https://duffel.com/airlines).

- **Fees:** 3 USD per confirmed order, 1 % managed content, 2 USD per ancillary, 2 % FX, and
  **0.005 USD per search above a 1 500 : 1 search-to-order ratio** (cl. 2.3: zero orders count as
  one, so 1 500 free searches a month, then 10 000 searches ≈ 42.50 USD). Enterprise: "bespoke
  pricing", "volume discounts", "use your own IATA accreditation", via sales.
- **Freshness:** live NDC / direct-connect shopping: seconds.
- **Coverage:** easyJet, Vueling, Transavia (Direct Connect), TAP (via Travelport), Volotea,
  Norwegian, Pegasus listed. **Ryanair and Wizz Air are not listed.**
- **Terms (verbatim):** cl. 2.5(d) forbids to "access or use the Services for metasearch purposes
  (including to build a metasearch on top of the Duffel Platform and/or to redistribute to a
  metasearch platform)"; 2.5(a) no "republish, download, display, transmit, or distribute"; 2.5(k)
  no marketing with Supplier Data "unless such Supplier has given its prior written consent for
  your specific use". No exception process is written; the only doors are a signed Order Form (cl.
  1, 4.1) and the airline's written consent (2.5(k)).
- **Verdict:** usable only with a signed Order Form that names our use ("publishing selected fares
  with a booking link") and, for marketing with an airline's fares, that airline's consent. Ask
  Duffel sales; expect "no" from their standard product and "maybe" from enterprise. Without Ryanair
  and Wizz it covers about half our observations.

### 2.4 Google Flights through a scraping API (SerpApi, Apify) — breaks D13

- **What:** [SerpApi's Google Flights API](https://serpapi.com/blog/tag/google-flights-api) and a
  dozen [Apify actors](https://apify.com/thirdwatch/google-flights-scraper) return Google Flights
  results as JSON: live, every airline, price calendars, "Explore" (anywhere from LIS under X €).
- **Freshness:** live at query time: this is exactly the competition's tool, automated.
- **Cost:** SerpApi plans from about 25 USD/month for 1 000 searches (third-party summaries;
  SerpApi's own page should be checked); Apify actors from 0.12 to 3.50 USD per 1 000 itineraries
  (seller-listed). 375 routes × 3 months × 48 runs/day is 54 000 searches a day: not viable as the
  bulk collector; viable as a **live check and a hot-list probe**: a few hundred searches a day,
  under 100 USD/month.
- **Terms and risk:** Google's Terms (2026-07-30) forbid "using automated means to access content
  from any of our services in violation of the machine-readable instructions on our web pages";
  the vendor does the scraping, we buy the output. The legal exposure for a Portuguese content site
  that links to the airline is low in practice but not zero, and it contradicts D13 and the
  privacy/terms posture the site advertises. Traceability (`data-obs`) is unaffected: a Google
  Flights price is a dated observation with a link, like any other.
- **Verdict:** the fastest practical route to live fares for every carrier, at the cost of a rule.
  If Miguel accepts the risk, use it only for the hot list and the live check, never as the baseline
  source, and record the decision in DECISIONS.

### 2.5 Airlines' own fare calendars — breaks D13

- **What:** Ryanair's `farfnd/v4` cheapest-fare-per-day endpoint (the one behind ryanair.com's
  "fare finder"), and the equivalents Wizz Air and easyJet pages call; no key needed. Dozens of
  [Apify scrapers](https://apify.com/euroscrape/ryanair-low-fares) and an [npm wrapper](https://cdn.jsdelivr.net/npm/@2bad/ryanair@8.0.0/README.md)
  ("unofficial… subject to Ryanair's API terms") use them.
- **Freshness:** live, minutes. **Coverage:** the airline's own fares, base price, adults only,
  0–180 days ahead. For Ryanair and Wizz this is the *only* live source short of OAG.
- **Cost:** 0 €.
- **Risk:** Ryanair's terms forbid automated access and it litigates: a US jury found Booking.com
  liable under the Computer Fraud and Abuse Act ([Travel Weekly](https://travelweekly.co.uk/news/air/ryanair-wins-screenscraping-case-against-booking-com)).
  Those cases were about unauthorised resale; a content site sending the traveller to ryanair.com
  is a different posture, but the terms are the same. Endpoints change and bot walls appear without
  notice (easyJet blocked the 2026-10-15 fetch). Ryanair's "Approved OTA" programme ([Etraveli](https://corporate.ryanair.com/news/ryanair-announces-approved-ota-partnershipwith-etraveli-group-including-mytrip-gotogate-flightnetwork/),
  Braganza) is for resellers, not media; there is no partner data feed to apply for.
- **Verdict:** the cheapest live feed for our two biggest low-cost carriers and a clear D13 breach.
  If chosen: low volume (the hot list only), honest `source` names, and a one-line
  user-agent that identifies us, so a cease-and-desist is the worst case, not a surprise.

### 2.6 Closed doors (checked again 2026-10-24, unchanged)

- **Skyscanner Travel API:** "minimum of 100K monthly active users", established businesses with a
  pre-built product ([Skyscanner partner support](https://skyscannerpartnersupport.zendesk.com/hc/en-us/articles/25486916837405-What-is-the-acceptance-criteria-for-being-eligible-for-the-Car-Hire-API)).
- **Travelpayouts / Aviasales Flight Search API:** 50 000 MAU, "requests from projects that do not
  meet this requirement are not considered, and we do not make exceptions"; no paid tier exists
  ([access requirements](https://support.travelpayouts.com/hc/en-us/articles/210995808-How-to-get-access-to-the-Aviasales-Search-API)). Its
  usage rules also forbid collecting data from search results, so it would not be a collector anyway.
- **Kiwi.com Tequila:** invitation only since 2024-05-30 ([Kiwi.com](https://media.kiwi.com/articles-and-interviews/better-for-business-kiwi-com-takes-a-new-approach-to-partnerships/)).
- **Amadeus Self-Service:** decommissioned 2026-07-17; Enterprise is accreditation-gated and
  consultant-led. **Sabre / Travelport:** custom quotes, accreditation, and no Ryanair/Wizz on a GDS.
- **KAYAK Price Insights, Skyscanner Indicative Prices:** caches like Aviasales', with their own
  tracked links. No speed gain.
- **TAP NDC direct API:** for agencies that sell; a white-label for small agencies; not a fare feed.

---

## 3. The "same place as the link" rule (D13) under a second source

D13 says the price shown must come from the same place as the link, because a traveller who clicks
must find the price we printed. A live source changes the question: if OAG or Google Flights tells
us Ryanair sells LIS–MXP for 39 € *now*, the honest link is **to the airline or OTA that sells it**,
not to an Aviasales search that may show 61 €. Options:

1. **Live source for detection, Aviasales for the link, Aviasales `price_now` as the gate**
   (today's `pipeline.price_now` is already the live check): publish only when Aviasales confirms
   the same or a lower fare. Keeps every rule, loses the fares Aviasales never saw (most of the
   speed gain on thin routes).
2. **Live source for detection and the link goes to the seller**, Travelpayouts partner link when
   the seller is in the Aviasales network, else a plain link to the airline with no commission.
   Fastest and most honest for the traveller; some posts earn nothing. Needs a `link_source` on the
   deal and the caption's disclosure text per link kind.
3. **Second affiliate network for the airline links** (Ryanair, Wizz, TAP run programmes through
   Awin and similar): more revenue, more compliance surface (each network's rules), and a second
   kind of `marker=`-style link to keep out of hand-built URLs.

Recommendation: 2, with 1 as the automatic fallback when Aviasales does confirm the fare. Write it
as a D-entry before the first live source lands.

---

## 4. Free and immediate: shorten our own pipeline (recommendation 1–3 in detail)

These need no new source, no money and no rule change, and together they cut hours from the
typical case.

1. **Page the reviewer.** The minute `detect` stores a candidate, send Miguel a Telegram message
   (a private chat, the same bot as D38) with the snapshot's key facts and two inline buttons
   (approve / reject) that write D26 events through the review Function. Nothing else changes:
   the applier still owns the status, the live check still runs. Today a candidate waits for
   someone to open the review page; the competition's reviewer is the finder.
2. **Post to Telegram at approval time, not at the next run.** `apply_review_events` →
   `publish_due` already run in order in `cli._run_steps`; the gap is that approval happens between
   runs. Give the review Function (or the Telegram bot) the right to trigger `workflow_dispatch`
   (`full: false`) right after writing an approve event, so the run that applies it starts within
   a minute. The Worker already holds a token that can dispatch (D41).
3. **Bounded auto-approve.** A new D26 *writer* (never a status change itself): when a candidate is
   `confidence: high`, `new_low: true`, nonstop both ways, the live check passes with
   `found_at` under N hours, and the route is not on an exclusion list, write an approve event
   with `actor: auto`. The applier treats it like any other event; a daily cap and a kill switch in
   config; every auto-approval is reported in the run summary. This is what "the algorithm posts"
   means at Secret Flying and Going. Start at zero per day (dry run that only reports what it would
   have approved), raise when the backtest agrees.
4. **Run every 30 min.** The Worker's cron `17 */2 * * *` → `*/30 * * * *`; `RUN_GAP_WARNING` and the
   fallback window follow (`tests/test_scheduler.py`). Cost: 48 runs × ~2 min = about 2 900
   Actions minutes a month, about 900 over the free 2 000 at 0.008 USD/min ≈ **7 USD/month**; or
   move the collector to a 5 €/month VPS with a systemd timer and keep Actions for the full path.
   Also the API cap: 375 routes × 3 months = 1 125 calls at 550/min is ~2 min, fine at 48 runs/day
   (54 000 calls/day; the Data API states no daily cap, confirm with support@travelpayouts.com).
5. **Use freshness we already have.** Ask the GraphQL `found_at` for every candidate (D43 does, for
   up to 60 per run) and show "visto há 1 h" vs "visto há 3 dias" on the review page; sort the hot
   list by it. Poll `special_offers_round_trip` (Aviasales' own "abnormally low" list, 23 offers
   from Lisbon on 2026-10-15) every run as a cross-check column, never as a price.
6. **Two daily passes** (06:00 and 18:00 Lisbon) so far months are seen twice a day: +1 080
   requests, +2 min once a day.
7. **Measure the competition's latency, legally.** Subscribe to deferias.pt's and similar public
   Telegram channels / RSS with the bot, store (channel, time, route, price) in `meta`-style
   tables, and compute "how long after their post did our data show the same fare, if ever". That
   is the benchmark for every change above. Reading a public channel is not scraping a booking site.

---

## 5. What Miguel has to do (nobody else can)

1. **Decide on D13.** Keep it (then recommendations 1–5 and the OAG/Skyscanner/Duffel talks), or
   accept scraping-grade sources for the hot list and the live check (then add 6–7 with the
   safeguards in §2.4–2.5 and record it as a D-entry).
2. **E-mail three vendors this week** (drafts: [`2026-10-24-vendor-emails.md`](2026-10-24-vendor-emails.md)): OAG (Retailer PPS / alerts, pilot
   price, publishing rights), Skyscanner Data Products (Live Pricing Services, publishing and link
   terms), Duffel sales (Order Form covering publication of selected fares with a link; airline
   consents under cl. 2.5(k)).
3. **Budget line:** 7 USD/month for Actions minutes (or a VPS) now; the vendor quotes later.
4. **A private Telegram chat id** for the paging bot (same bot token as D38).

---

## 6. Sources

Vendor pages read directly: [Duffel pricing](https://duffel.com/pricing), [Duffel services agreement](https://duffel.com/services-agreement),
[Duffel airlines](https://duffel.com/airlines) (2026-10-24). Skyscanner's
[Data Products Terms](https://www.skyscanner.net/media/data-products-terms-and-conditions) rendered no text to the fetcher.

Search results used: [Skyscanner Travel API contact](https://www.partners.skyscanner.net/contact/travel-api),
[Skyscanner eligibility](https://skyscannerpartnersupport.zendesk.com/hc/en-us/articles/25486916837405-What-is-the-acceptance-criteria-for-being-eligible-for-the-Car-Hire-API),
[Travelpayouts Search API access](https://support.travelpayouts.com/hc/en-us/articles/210995808-How-to-get-access-to-the-Aviasales-Search-API),
[Travelpayouts Data API](https://support.travelpayouts.com/hc/en-us/articles/203956163),
[Travelpayouts GraphQL](https://support.travelpayouts.com/hc/en-us/articles/4417975783314-Aviasales-GraphQL-for-access-to-Flights-Data-API),
[Kiwi.com partnerships](https://media.kiwi.com/articles-and-interviews/better-for-business-kiwi-com-takes-a-new-approach-to-partnerships/),
[Amadeus Self-Service shutdown](https://dev.to/ishemah/amadeus-self-service-shut-down-on-july-17-heres-a-drop-in-replacement-for-flight-prices-1npn),
[SerpApi Google Flights](https://serpapi.com/blog/tag/google-flights-api),
[SerpApi pricing change 2026-09](https://costbench.com/changelog/serpapi-search-plan-added-2026-09/),
[Apify Google Flights scraper](https://apify.com/thirdwatch/google-flights-scraper),
[Apify Ryanair low fares](https://apify.com/euroscrape/ryanair-low-fares),
[@2bad/ryanair README](https://cdn.jsdelivr.net/npm/@2bad/ryanair@8.0.0/README.md),
[Ryanair v Booking.com](https://travelweekly.co.uk/news/air/ryanair-wins-screenscraping-case-against-booking-com),
[Ryanair Approved OTA (Etraveli)](https://corporate.ryanair.com/news/ryanair-announces-approved-ota-partnershipwith-etraveli-group-including-mytrip-gotogate-flightnetwork/),
[OAG Retailer PPS](https://www.oag.com/retailer-pps), [OAG Altus](https://www.oag.com/altus-data),
[OAG acquires Infare](https://www.businesswire.com/news/home/20230728180571/en/OAG-Acquires-Infare-and-Receives-New-Investment-from-Vitruvian-Partners),
[Skyscanner data products (PhocusWire)](https://www.phocuswire.com/Skyscanners-airfare-data-opened-to-airlines-airports-and-marketers-for-B2B-Big-Data-access),
[Going methodology (Nomadic Matt)](https://www.nomadicmatt.com/travel-blogs/going-review/),
[Secret Flying vs Going](https://going.com/comparison/secret-flying),
[TAP NDC (Travelextra)](https://www.travelextra.ie/marta-alves-of-tap-air-portugal-at-the-itaa-conference-2025/),
[Sabre/Travelport cost estimates](https://www.oneclickitsolution.com/blog/gds-api-integration-cost-2026).
Third-party price figures are the vendors' or bloggers' claims on the day, not quotes.

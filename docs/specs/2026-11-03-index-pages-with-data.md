# Spec: Index only the pages that have data of their own

Status: draft for Miguel's decision · Origin: research of 2026-11-03
(`docs/research/2026-11-03-site-and-algorithm-improvements.md`, findings 7 and 8, section 2.5) ·
Milestone: M3 Website · Vocabulary: `GLOSSARY.md` · Prior decisions: D23, D30, D34, D35, D45

## Problem Statement

The site is generated from data: a page per route (375), per destination (159 hubs) and per
origin. Google's spam policies name the risk of that model. Doorway abuse includes
"substantially similar pages that are closer to search results than a clearly defined,
browseable hierarchy". Scaled content abuse is many pages made "without adding value for users",
however they were produced. Google's test is purpose and value, and price information and useful
navigation count as value. A route page with a calendar, a typical low and recent low prices
passes it. A route page with no price at all does not.

On 2026-11-03:

- the sitemap held 560 URLs: 375 route pages and 159 hubs among them;
- **108 routes have never had a single price** (`routes.last_observed_at` null). Their pages, such
  as `/voos/faro-katowice/`, say "Não há preços recentes nesta rota" in every section. All 108 are
  indexed and in the sitemap;
- **35 of 158 destinations have no route that ever had a price.** Their hubs, such as
  `/destinos/katowice/`, are indexed too;
- route pages and hubs never set `noindex`. Only promotions, ponte pages, content drafts and empty
  listings do (D34 lets every page decide its own).

A fifth of the indexed site is empty pages. That invites a site-wide quality judgement and spends
crawl on pages nobody should land on. Monetisation depends on organic traffic (Aviasales pays
about 1 % of a ticket, research finding 8), so this is also the monetisation work.

## Solution

1. **A route page is indexed only when it has data of its own:** a current cheapest price, or a
   calendar date, or at least one month with a typical low shown (mature, D40), or a promotion
   live or still kept (`site.expired_promotions_days`). Otherwise it is `noindex`. The sitemap
   drops it by itself, since `sitemap.ts` reads the built pages' robots tags. The page keeps
   working (HTTP 200, same URL, D35's no-404 rule): breadcrumbs, the rules, the partner's search
   button, the Eurostat demand note (D45), and one plain sentence of why there is nothing yet
   ("Ainda não vimos preços nesta rota: aparece aqui assim que um viajante encontrar um.").
2. **A destination hub is indexed only when at least one of its routes is indexed, or when it
   has a reviewed itinerary** (D33: original content of its own). Origin pages stay indexed: they
   are the hierarchy.
3. **Navigation stays a hierarchy, not a list of empty doors.** Origin pages and hubs list the
   routes with data first, as today, and the price-less ones after them in a compact "Ainda sem
   preços" list of plain links (city, arrival airport), not as cards with empty price slots.
4. **Measured in Search Console.** Before shipping, Miguel records the indexed and "crawled, not
   indexed" counts. Four weeks after, he records them again. The pages leave the index on their
   own as Google recrawls them.

When a route gets its first price, its page becomes indexable at the next full path, because the
page decides from the contract's data at build time.

## User Stories

1. As a visitor arriving from search, I want to land only on pages that show real prices or real
   content, so that a search result never leads to an empty page.
2. As a visitor browsing an origin page, I want routes with prices first and the routes without
   prices as a short list of links, so that I can still find every route we watch.
3. As Miguel, I want price-less route pages and empty hubs kept online but out of the index, so
   that old links keep working and the site is not judged by its emptiest fifth.
4. As Miguel, I want a page to become indexable by itself as soon as its route has data, so that
   I never manage an index list by hand.
5. As Miguel, I want before-and-after numbers from Search Console, so that I know the change did
   what it was meant to.

## Implementation Decisions

- **One pure rule** in `web/src/lib/indexable.ts`: `routeIndexable(route)` and
  `hubIndexable(routes, hasItinerary)`, both from contract fields only (`cheapest`, `calendar`,
  `months[].typical_low`, which the export leaves null below `min_baseline_days`,
  `counts.promotions_live` / `promotions_expired`), and for hubs the reviewed itinerary read
  through `src/collections.ts` (`itineraryFor`, the review gate, D33). Pages pass the result to
  `Base.astro`'s `noindex`. No list of slugs anywhere; the sitemap is unchanged (it already
  follows the pages, D34).
- **No contract change.** Every input is already exported or already in the content collections.
- **Dormant routes** (D23) with an old typical low keep their page indexed: that history is data
  of its own. A dormant route that never had a price is `noindex` like any other.
- **Copy** in pt-PT through the page templates (no prices, pt-PT lint); the "Ainda sem preços" list
  uses the route's `path` from the contract (the web package never builds a path).
- **JSON-LD:** a `noindex` page keeps its breadcrumbs. It gets no `Offer` (it has no price anyway).
- **Fingerprint:** unchanged in kind. The rule reads exported data, so a route's first price
  changes `site_data` and triggers the full path as today.

## Testing Decisions

- `web/test/indexable.test.ts`: each condition alone makes a route indexable, none makes it
  `noindex`; a hub with one indexable route, with only a reviewed itinerary, with neither.
- Fixture build (`web/test/seo.test.ts`): a price-less fixture route renders `noindex` and is
  absent from `sitemap.xml`; a priced one is present; the price-less page still links to its
  origin and hub and shows the explanatory sentence. If the committed fixtures have no price-less
  route, add one in a test-only build like `scale.test.ts` does (no hand-edit of the fixtures).
- `tests/test_crawl.py` keeps passing: no old URL 404s.
- Origin page: priced routes as cards, price-less ones in the compact list, every route linked
  once (`web/test/route-pages.test.ts`).

## Out of Scope

- Deleting or redirecting price-less pages: they stay (D23: routes are never deleted; D35: no
  404).
- Changing which routes are collected or discovered.
- Rewriting route page copy beyond the one explanatory sentence.
- Paid SEO tools. Search Console is free and Miguel's.

## Further Notes

- The numbers move every day: 219 routes were observed in the last 7 days on 2026-11-03, and
  seasonal routes come and go. The rule is about data, not dates, so it needs no tuning.
- Google's policies were revised during 2026, with enforcement updates reported in June, August
  and September. The rule above is conservative on purpose: it removes only pages with nothing of
  their own.

## Tickets

Spec issue #76. Tickets (opened 2026-11-03, `needs-decision`):

1. #83 M3 Route pages without data of their own are `noindex` and leave the sitemap
2. #84 M3 Hubs without an indexed route or itinerary are `noindex`; origin pages and hubs list price-less routes compactly

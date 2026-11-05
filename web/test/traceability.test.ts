// Never fabricate prices (D2), on the Astro site: every price string on every built page (text
// and attribute values, e.g. <title> and og:description) must sit in or under an element that
// references what it comes from, and equal one of that reference's amounts in the contract:
// - data-obs="<id>": the price of that stored observation (offers, expiry rechecks, low prices,
//   calendar days, other sources' prices of the same trip, D47);
// - data-deal="<id>": the promotion's offer price, its typical low, or its expiry recheck price;
// - data-route="<KEY>": a month's typical low or average on that route, or its cheapest offer.
// The nearest element carrying any of these attributes decides. Mirrors tests/test_traceability.py.
import { describe, expect, it } from "vitest";
import type { Promotion } from "../src/lib/contract";
import { priceInsight } from "../src/lib/price-insight";
import { pagePromotions } from "../src/lib/promotion";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { builtPages, pageSource } from "./html";
import { traceableAmounts, untraceable } from "./trace";

describe("traceability of prices", () => {
  const data = loadSiteData(FIXTURES_DIR);
  const amounts = traceableAmounts(data);

  it("every price on every built page traces to the contract", () => {
    const checked = new Map<string, number>();
    const problems: string[] = [];
    for (const path of builtPages()) {
      const result = untraceable(pageSource(path), amounts);
      checked.set(path, result.checked);
      problems.push(...result.problems.map((p) => `${path}: ${p}`));
    }
    expect(problems).toEqual([]);
    // The checker saw the prices it guards: one per card on the home page; on a live promotion 11
    // (title, OpenGraph and Twitter title and descriptions, the one-line summary (D46), price,
    // typical low, the JSON-LD offer price and description), one per other source (D47) and the
    // verdict's typical low on data-route when its month can judge (D58); on an expired one its
    // old price, its typical low and the recheck's price when the reason names it.
    const pages = pagePromotions(data);
    const det = data.meta.detector;
    const verdicts = (p: Promotion) => {
      const route = data.routes.routes.find((r) => r.key === p.route)!;
      return priceInsight(p.latest?.price ?? p.offer.price, route, p.offer.departure, det) ? 1 : 0;
    };
    const expected = pages.length + pages.reduce((n, p) => n + (p.live
      ? 11 + (p.also_seen?.length ?? 0) + verdicts(p)
      : 2 + (p.expired?.reason?.includes("€") ? 1 : 0)), 0);
    expect(pages.filter((p) => p.live).map(verdicts)).toEqual([1, 1]);   // both live fixtures judged
    const promos = ["/", ...[...checked.keys()].filter((p) => p.startsWith("/promos/"))];
    expect(promos.reduce((n, p) => n + checked.get(p)!, 0)).toBe(expected);
    expect(expected).toBeGreaterThan(100);              // the fixtures' 29 promotion pages (#52)
    // Route pages: at least every calendar day, typical low and low price (two prices each).
    const routes = data.routes.routes;
    const lows = Object.values(data.lowPrices).reduce((n, f) => n + f.rows.length, 0);
    const minimum = routes.reduce((n, r) => n + r.calendar.length
      + r.months.filter((m) => m.typical_low != null).length * 2, 0) + lows;
    const onRoutePages = routes.reduce((n, r) => n + checked.get(r.path)!, 0);
    expect(onRoutePages).toBeGreaterThanOrEqual(minimum);
    // Origin pages show every route's cheapest price.
    const onOriginPages = data.origins.origins.reduce((n, o) => n + checked.get(o.path)!, 0);
    expect(onOriginPages).toBe(routes.filter((r) => r.cheapest && r.status === "active").length);
    // The explorer shows Lisboa's destinations (Madeira only): price and typical low each (D31).
    expect(checked.get("/explorar/")).toBe(2);
  });

  it("the checker rejects a price without a reference, with a wrong one, or an unknown id", () => {
    const bad = `<html><body>
      <p>Desde 86 €</p>
      <p data-obs="37258">Desde 87 €</p>
      <p data-deal="999">Desde 86 €</p>
      <p data-deal="397"><span>Habitual: 111,50&nbsp;€</span></p>
      <p>Por <b>99<span>&nbsp;€</span></b></p>
    </body></html>`;
    const { checked, problems } = untraceable(bad, amounts);
    expect(checked).toBe(5);
    expect(problems).toHaveLength(4);
  });

  it("checks JSON-LD prices too: a number, an amount of the block's own reference", () => {
    const ld = (attrs: string, offer: object) =>
      `<script type="application/ld+json" ${attrs}>${JSON.stringify({ "@type": "Trip", offers: { "@type": "Offer", ...offer } })}</script>`;
    const html = `<html><head>
      ${ld('data-obs="71428"', { price: 58 })}
      ${ld("", { price: 58 })}
      ${ld('data-obs="71428"', { price: 59 })}
      ${ld('data-obs="71428"', { price: "58" })}
      ${ld('data-obs="999999"', { price: 58 })}
      ${ld('data-obs="71428"', { description: "Por 59 € ida e volta" })}
    </head><body></body></html>`;
    const { checked, problems } = untraceable(html, amounts);
    expect(checked).toBe(6);
    expect(problems).toHaveLength(5);
    expect(problems.join("\n")).toContain("no data-obs/data-deal/data-route on its <script>");
  });
});

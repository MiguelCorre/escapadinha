// Never fabricate prices (D2), on the Astro site: every price string on every built page (text
// and attribute values, e.g. <title> and og:description) must sit in or under an element that
// references what it comes from, and equal one of that reference's amounts in the contract:
// - data-obs="<id>": the price of that stored observation (offers, expiry rechecks, low prices,
//   calendar days);
// - data-deal="<id>": the promotion's offer price, its typical low, or its expiry recheck price;
// - data-route="<KEY>": a month's typical low or average on that route, or its cheapest offer.
// The nearest element carrying any of these attributes decides. Mirrors tests/test_traceability.py.
import { describe, expect, it } from "vitest";
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
    // The checker saw the prices it guards: 2 on the home page, 6 on the live promotion (title,
    // descriptions, price, typical low), 3 on the expired one (old price, recheck price, typical low).
    const promos = ["/", ...[...checked.keys()].filter((p) => p.startsWith("/promos/"))];
    expect(promos.reduce((n, p) => n + checked.get(p)!, 0)).toBe(11);
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
  });

  it("the checker rejects a price without a reference, with a wrong one, or an unknown id", () => {
    const bad = `<html><body>
      <p>Desde 86 €</p>
      <p data-obs="2792">Desde 87 €</p>
      <p data-deal="999">Desde 86 €</p>
      <p data-deal="3"><span>Habitual: 153,50&nbsp;€</span></p>
      <p>Por <b>99<span>&nbsp;€</span></b></p>
    </body></html>`;
    const { checked, problems } = untraceable(bad, amounts);
    expect(checked).toBe(5);
    expect(problems).toHaveLength(4);
  });
});

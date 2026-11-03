// Which route pages and destination hubs search engines may index (src/lib/indexable.ts, #76):
// only those with data of their own. Inputs are small hand-made routes; each condition is tried
// alone, then none of them.
import { describe, expect, it } from "vitest";
import type { Route } from "../src/lib/contract";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { hubIndexable, routeIndexable } from "../src/lib/indexable";

function route(over: Partial<Route> = {}): Route {
  return {
    key: "FAO-KTW", origin: "FAO", destination: "KTW", city: "Katowice", city_en: "Katowice",
    kind: "europe", status: "active", airports: ["KTW"],
    rules: { direct_only: true, min_nights: 2, max_nights: 3, max_transfers: 0 },
    path: "/voos/faro-katowice/", months: [], cheapest: null, calendar: [],
    counts: { observations: 0, low_prices: 0, promotions_live: 0, promotions_expired: 0 },
    discovered_at: null, last_observed_at: null, demand: null, ...over,
  };
}

const counts = (live: number, expired: number): Route["counts"] =>
  ({ observations: 3, low_prices: 0, promotions_live: live, promotions_expired: expired });

const empty = route();
const withCheapest = route({ cheapest: { obs: 1, route: "FAO-KTW", price: 80, departure: "2026-11-20",
  return: "2026-11-23", nights: 3, airline: "FR", transfers: 0, return_transfers: 0, arrival_airport: "KTW",
  found_date: "2026-10-13", fetched_at: "2026-10-13T20:15:00Z", baggage: null } });
const withCalendar = route({ calendar: [{ dep: "2026-11-20", ret: "2026-11-23", obs: 2, price: 80 }] });
const withTypicalLow = route({ months: [{ month: "2026-11", typical_low: 75, average: 81, days: 9 }] });

describe("routeIndexable", () => {
  it("indexes a route page with any data of its own", () => {
    expect(routeIndexable(withCheapest)).toBe(true);
    expect(routeIndexable(withCalendar)).toBe(true);
    expect(routeIndexable(withTypicalLow)).toBe(true);
    expect(routeIndexable(route({ counts: counts(1, 0) }))).toBe(true);
    expect(routeIndexable(route({ counts: counts(0, 1) }))).toBe(true);
  });

  it("keeps a page out of the index when it has nothing to show", () => {
    expect(routeIndexable(empty)).toBe(false);
  });

  it("does not count months still collecting data, demand or a dormant past", () => {
    const collecting = route({ months: [{ month: "2026-11", typical_low: null, average: null, days: 3 }] });
    expect(routeIndexable(collecting)).toBe(false);
    const busy = route({ demand: { pax_month: 50_000, period: "2024-12", months: [] } });
    expect(routeIndexable(busy)).toBe(false);
    const dormant = route({ status: "dormant", last_observed_at: "2026-09-01T10:00:00Z" });
    expect(routeIndexable(dormant)).toBe(false);
    expect(routeIndexable(route({ status: "dormant", months: withTypicalLow.months }))).toBe(true);
  });

  it("indexes every route of the committed fixtures", () => {
    const data = loadSiteData(FIXTURES_DIR);
    for (const r of data.routes.routes) expect(routeIndexable(r), r.key).toBe(true);
  });
});

describe("hubIndexable", () => {
  it("indexes a hub with one indexable route among empty ones", () => {
    expect(hubIndexable([empty, withCalendar], false)).toBe(true);
  });

  it("indexes a hub with a reviewed itinerary even when no route has data", () => {
    expect(hubIndexable([empty], true)).toBe(true);
  });

  it("keeps a hub out of the index when neither", () => {
    expect(hubIndexable([empty, route({ key: "LIS-KTW" })], false)).toBe(false);
    expect(hubIndexable([], false)).toBe(false);
  });
});

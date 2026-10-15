// The route, origin and destination views (src/lib/routes.ts, #14): what those pages show,
// derived from the contract. Inputs are small hand-made routes; expected values are worked out
// by hand (calendar weekdays checked against a 2026 calendar).
import { describe, expect, it } from "vitest";
import type { LowPriceRow, Route, SiteData } from "../src/lib/contract";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import {
  bestMonths, calendarMonths, monthRows, originGroups, routeLowPrices, rulesText, typicalLowRule,
} from "../src/lib/routes";

const fixtures = loadSiteData(FIXTURES_DIR);

function route(over: Partial<Route> = {}): Route {
  return {
    key: "LIS-PAR", origin: "LIS", destination: "PAR", city: "Paris", city_en: "Paris",
    kind: "europe", status: "active", airports: ["ORY", "BVA"],
    rules: { direct_only: true, min_nights: 2, max_nights: 10, max_transfers: 0 },
    path: "/voos/lisboa-paris/", months: [], cheapest: null, calendar: [],
    counts: { observations: 0, low_prices: 0, promotions_live: 0, promotions_expired: 0 },
    discovered_at: null, last_observed_at: null, ...over,
  };
}

describe("monthRows", () => {
  it("gives the typical low and the average, or says there is not enough data yet", () => {
    const rows = monthRows(route({
      months: [
        { month: "2026-11", typical_low: 87, average: 95.5, days: 6 },
        { month: "2026-12", typical_low: null, average: null, days: 2 },
      ],
    }), 4);
    expect(rows).toEqual([
      { month: "2026-11", label: "novembro de 2026", typicalLow: "87 €", average: "95,50 €", days: "6 dias" },
      { month: "2026-12", label: "dezembro de 2026", typicalLow: null, average: null, days: "2 de 4 dias" },
    ]);
  });
});

describe("typicalLowRule", () => {
  it("says how many days a month needs, and which days count (D40)", () => {
    expect(typicalLowRule({ min_baseline_days: 7, min_dates_per_day: 2 })).toBe(
      "Precisamos de pelo menos 7 dias de dados num mês, contando só os dias com preços para 2 ou mais "
      + "datas de partida, antes de dizer o que é habitual.");
    // An export made before D40 has no min_dates_per_day: every day counted.
    expect(typicalLowRule({ min_baseline_days: 4 })).toBe(
      "Precisamos de pelo menos 4 dias de dados num mês antes de dizer o que é habitual.");
  });
});

describe("bestMonths", () => {
  it("are the months with the lowest typical low, cheapest first, at most three", () => {
    const r = route({
      months: [
        { month: "2026-10", typical_low: 120, average: 130, days: 5 },
        { month: "2026-11", typical_low: 87, average: 95, days: 6 },
        { month: "2026-12", typical_low: null, average: null, days: 1 },
        { month: "2027-01", typical_low: 64.5, average: 70, days: 4 },
        { month: "2027-02", typical_low: 99, average: 101, days: 4 },
      ],
    });
    expect(bestMonths(r)).toEqual([
      { month: "2027-01", label: "janeiro de 2027", typicalLow: "64,50 €" },
      { month: "2026-11", label: "novembro de 2026", typicalLow: "87 €" },
      { month: "2027-02", label: "fevereiro de 2027", typicalLow: "99 €" },
    ]);
  });

  it("are none while no month has enough data", () => {
    expect(bestMonths(route({ months: [{ month: "2026-12", typical_low: null, average: null, days: 1 }] })))
      .toEqual([]);
  });
});

describe("calendarMonths", () => {
  it("lays the cheapest price per departure day out in Monday-first weeks", () => {
    const r = route({
      calendar: [
        { dep: "2026-11-02", ret: "2026-11-05", obs: 11, price: 70 },
        { dep: "2026-11-18", ret: "2026-11-25", obs: 12, price: 51 },
        { dep: "2026-12-01", ret: "2026-12-04", obs: 13, price: 88.5 },
      ],
    });
    const [nov, dec] = calendarMonths(r);
    expect(nov.label).toBe("novembro de 2026");
    // 1 November 2026 is a Sunday: six empty cells, then the 1st.
    expect(nov.weeks[0].map((c) => c?.day ?? null)).toEqual([null, null, null, null, null, null, 1]);
    expect(nov.weeks).toHaveLength(6);           // 1 Nov (Sun) .. 30 Nov (Mon)
    const second = nov.weeks[1][0]!;
    expect(second).toMatchObject({ day: 2, price: { obs: 11, text: "70 €", cheapest: false } });
    expect(second.price!.title).toBe("Partida seg, 2 nov, regresso qui, 5 nov");
    const cheapest = nov.weeks.flat().filter((c) => c?.price?.cheapest);
    expect(cheapest.map((c) => c!.day)).toEqual([18]);
    expect(nov.weeks.flat().filter((c) => c?.price)).toHaveLength(2);
    // 1 December 2026 is a Tuesday.
    expect(dec.weeks[0][1]).toMatchObject({ day: 1, price: { obs: 13, text: "88,50 €", cheapest: true } });
  });

  it("is empty without prices", () => {
    expect(calendarMonths(route())).toEqual([]);
  });
});

describe("routeLowPrices", () => {
  const row = (obs: number, dest: string, price: number, dep: string, typical: number,
    link: string | null = `https://example.com/parceiro/site-low-${obs}`): LowPriceRow =>
    [obs, dest, price, dep, "2026-11-30", "2026-10-12", "2026-10-13T09:00Z", "FR", 0, "BVA", typical, link];
  const data = (rows: LowPriceRow[]): SiteData => ({
    ...fixtures,
    lowPrices: { LIS: { version: 1, origin: "LIS", generated_at: "2026-10-13T09:00Z", run: 1, cols: [], rows, truncated: 0 } },
  });

  it("are the route's biggest discounts, at most five, by departure date, without promoted offers", () => {
    const rows = [
      row(1, "PAR", 80, "2026-11-20", 100),   // -20 %
      row(2, "PAR", 50, "2026-11-25", 100),   // -50 %
      row(3, "PAR", 70, "2026-11-10", 100),   // -30 %
      row(4, "PAR", 60, "2026-11-05", 100),   // -40 %: a live promotion's own offer
      row(5, "PAR", 84, "2026-11-01", 100),   // -16 %
      row(6, "PAR", 82, "2026-11-02", 100),   // -18 %
      row(7, "PAR", 85, "2026-11-03", 100),   // -15 %: the sixth biggest, left out
      row(8, "LON", 10, "2026-11-04", 100),   // another route
    ];
    const lows = routeLowPrices(data(rows), route(), new Set([4]));
    expect(lows.map((l) => l.obs)).toEqual([5, 6, 3, 1, 2]);
    const first = lows[0];
    expect(first).toMatchObject({
      route: "LIS-PAR", path: "/voos/lisboa-paris/",
      discount: "−16%", typicalLow: "100 €", month: "novembro",
      dates: "dom, 1 nov → seg, 30 nov", nights: "29 noites", airline: "Ryanair", stops: "voos diretos",
      airport: "Beauvais (BVA)", remote: true, foundOn: "12/10/2026", fetchedAt: "13/10/2026 às 10:00",   // 09:00Z, Lisbon summer time
      link: { href: "https://example.com/parceiro/site-low-5", text: "Ver voo e reservar", rel: "sponsored nofollow noopener" },
    });
    expect(first.price.text).toBe("84 €");
  });
});

describe("originGroups", () => {
  it("groups an origin's routes by kind, each sorted by the Portuguese city name", () => {
    const routes = [
      route({ key: "LIS-PAR", city: "Paris" }),
      route({ key: "LIS-AMS", destination: "AMS", city: "Amesterdão" }),
      route({ key: "LIS-FNC", destination: "FNC", city: "Madeira", kind: "domestic" }),
      route({ key: "OPO-BCN", origin: "OPO", destination: "BCN", city: "Barcelona" }),
      route({ key: "LIS-ATH", destination: "ATH", city: "Atenas" }),
    ];
    const groups = originGroups({ ...fixtures, routes: { version: 1, routes } }, "LIS");
    expect(groups.map((g) => [g.label, g.routes.map((r) => r.city)])).toEqual([
      ["Europa", ["Amesterdão", "Atenas", "Paris"]],
      ["Portugal", ["Madeira"]],
    ]);
  });
});

describe("rulesText", () => {
  it("says which offers count on the route", () => {
    expect(rulesText(route())).toBe("voos diretos, estadias de 2 a 10 noites");
    expect(rulesText(route({ rules: { direct_only: false, min_nights: 7, max_nights: 21, max_transfers: 1 } })))
      .toBe("até 1 escala em cada sentido, estadias de 7 a 21 noites");
    expect(rulesText(route({ rules: { direct_only: false, min_nights: 3, max_nights: 14, max_transfers: null } })))
      .toBe("com ou sem escalas, estadias de 3 a 14 noites");
  });
});

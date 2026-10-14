// The explorer's rules (src/lib/explorer.ts), shared by the server-rendered pages and the
// client island: the weekend rule, the ponte window, the filters and the one-per-destination
// list sorted by price, and the HTML of a result. Rows here are test data in the contract's
// shape (low-prices/<ORIGIN>.json); dates are checked against a calendar by hand.
import { describe, expect, it } from "vitest";
import { parse } from "node-html-parser";
import type { LowPriceRow, Ponte } from "../src/lib/contract";
import {
  NO_FILTERS, explore, fitsPonte, isWeekendTrip, resultsHtml, type Filters, type Places,
} from "../src/lib/explorer";
import { daysBetween } from "../src/lib/dates";

const DEZ_1: Pick<Ponte, "holiday" | "window"> = {
  holiday: { date: "2026-12-01", name: "Restauração da Independência", optional: false },
  window: { start: "2026-11-27", end: "2026-12-02" },
};
const PONTES = [{ slug: "1-dezembro-2026", ...DEZ_1 }];

function row(obs: number, dest: string, price: number, dep: string, ret: string,
  stops: number | null = 0, link: string | null = `https://example.com/parceiro/site-low-${obs}`): LowPriceRow {
  return [obs, dest, price, dep, ret, "2026-10-11", "2026-10-13T17:16Z", "FR", stops, dest === "PAR" ? "BVA" : dest, 80, link];
}

const ROWS: LowPriceRow[] = [
  row(1, "BCN", 53, "2026-11-27", "2026-11-29"),          // Fri -> Sun: weekend
  row(2, "BCN", 41, "2026-11-18", "2026-11-25"),          // Wed -> Wed, 7 nights
  row(3, "PAR", 70, "2026-11-28", "2026-12-01", 1),       // Sat -> Tue: the ponte, 1 stop
  row(4, "FNC", 60, "2026-12-04", "2026-12-07"),          // Fri -> Mon: weekend
  row(5, "LON", 95, "2026-11-27", "2026-12-02", null),    // ponte, stops unknown
];

const run = (f: Partial<Filters>) => explore(ROWS, { ...NO_FILTERS, ...f }, PONTES);
const obsOf = (f: Partial<Filters>) => run(f).map((r) => r.row[0]);

describe("weekend rule: out Friday or Saturday, back Sunday or Monday of the same weekend", () => {
  it.each([
    ["2026-11-27", "2026-11-29", true],   // Fri -> Sun
    ["2026-11-27", "2026-11-30", true],   // Fri -> Mon
    ["2026-11-28", "2026-11-29", true],   // Sat -> Sun
    ["2026-11-28", "2026-11-30", true],   // Sat -> Mon
    ["2026-11-26", "2026-11-29", false],  // Thu -> Sun
    ["2026-11-28", "2026-12-01", false],  // Sat -> Tue
    ["2026-11-29", "2026-11-30", false],  // Sun -> Mon
    ["2026-11-27", "2026-12-06", false],  // Fri -> the next Sunday
  ])("%s -> %s: %s", (dep, ret, expected) => {
    expect(isWeekendTrip(dep, ret)).toBe(expected);
  });
});

describe("ponte window: inside the travel window and over the holiday", () => {
  it.each([
    ["2026-11-27", "2026-12-01", true],   // Fri evening -> the holiday
    ["2026-11-28", "2026-12-02", true],   // Sat -> Wed morning
    ["2026-12-01", "2026-12-02", true],   // on the holiday itself
    ["2026-11-26", "2026-12-01", false],  // leaves before the window
    ["2026-11-28", "2026-12-03", false],  // back after it
    ["2026-11-27", "2026-11-29", false],  // a weekend that ends before the holiday
  ])("%s -> %s: %s", (dep, ret, expected) => {
    expect(fitsPonte(dep, ret, DEZ_1)).toBe(expected);
  });
});

describe("explore", () => {
  it("counts nights between the dates", () => {
    expect(daysBetween("2026-10-31", "2026-11-03")).toBe(3);
    expect(daysBetween("2027-03-26", "2027-03-29")).toBe(3);     // over the clock change
  });

  it("lists each destination once, at its cheapest, sorted by price", () => {
    const results = run({});
    expect(results.map((r) => r.row[0])).toEqual([2, 4, 3, 5]);
    expect(results[0].more).toBe(1);                             // BCN's other date
    expect(results[1].more).toBe(0);
  });

  it("filters by budget (inclusive), month of departure and nights", () => {
    expect(obsOf({ maxPrice: 60 })).toEqual([2, 4]);
    expect(obsOf({ month: "2026-12" })).toEqual([4]);
    expect(obsOf({ minNights: 3, maxNights: 4 })).toEqual([4, 3]);
  });

  it("keeps only direct flights when asked (unknown stops are not direct)", () => {
    expect(obsOf({ directOnly: true })).toEqual([2, 4]);
  });

  it("keeps weekends only, and a ponte's trips only", () => {
    expect(obsOf({ weekendOnly: true })).toEqual([1, 4]);
    expect(obsOf({ ponte: "1-dezembro-2026" })).toEqual([3, 5]);
    expect(obsOf({ ponte: "carnaval-2027" })).toEqual([]);      // not upcoming: nothing fits
  });
});

describe("resultsHtml", () => {
  const places: Places = {
    origin: "LIS",
    cities: { BCN: "Barcelona", PAR: "Paris", FNC: "Madeira", LON: "Londres <&>" },
    airports: { BVA: { name: "Beauvais", remote: true }, BCN: { name: "El Prat", remote: false } },
    airlines: { FR: "Ryanair" },
  };
  const html = () => parse(resultsHtml(run({}), places));

  it("traces each price to its observation and the typical low to the route", () => {
    const item = html().querySelector('[data-obs="3"]')!.closest("li")!;
    expect(item.getAttribute("data-route")).toBe("LIS-PAR");
    expect(item.querySelector('[data-obs="3"]')!.textContent.replace(/\s+/g, " ")).toBe("70 €");
    expect(item.querySelector("span[data-route]")!.getAttribute("data-route")).toBe("LIS-PAR");
    expect(item.querySelector("span[data-route]")!.textContent.replace(/\s+/g, " ")).toBe("80 €");
  });

  it("names the arrival airport (remote ones in the headline) and when the price was found", () => {
    const item = html().querySelector('li[data-route="LIS-PAR"]')!;
    expect(item.querySelector("h3")!.textContent).toBe("Paris (Beauvais)");
    expect(item.textContent).toContain("Chegada: Beauvais (BVA)");
    expect(item.textContent).toContain("Encontrado por um viajante a 11/10/2026 · visto por nós a 13/10/2026 às 18:16");
    expect(item.textContent).toContain("sáb, 28 nov → ter, 1 dez");
    expect(item.textContent).toContain("Ryanair · 1 escala");
    expect(item.textContent.replace(/\s+/g, " ")).toContain("Mínimo habitual em novembro: 80 €");
    const direct = html().querySelector('li[data-route="LIS-FNC"]')!;
    expect(direct.textContent).toContain("Ryanair · voos diretos");
  });

  it("links to the tracked partner link, sponsored, and escapes text", () => {
    const links = html().querySelectorAll('a[rel~="sponsored"]');
    expect(links.map((a) => a.getAttribute("href"))).toContain("https://example.com/parceiro/site-low-3");
    expect(resultsHtml(run({}), places)).toContain("Londres &lt;&amp;&gt;");
  });

  it("links the headline to the route page when the contract gives its path (D30)", () => {
    const linked = parse(resultsHtml(run({}), { ...places, paths: { PAR: "/voos/lisboa-paris/" } }));
    const a = linked.querySelector('li[data-route="LIS-PAR"] h3 a')!;
    expect(a.getAttribute("href")).toBe("/voos/lisboa-paris/");
    expect(a.textContent).toBe("Paris (Beauvais)");
    expect(linked.querySelector('li[data-route="LIS-BCN"] h3 a')).toBeNull();   // no path: no link
  });

  it("says the booking link is coming for a row without one (link budget, D24)", () => {
    const rows = [row(9, "BCN", 50, "2026-11-27", "2026-11-29", 0, null)];
    const doc = parse(resultsHtml(explore(rows, NO_FILTERS, PONTES), places));
    expect(doc.querySelectorAll("a")).toHaveLength(0);
    expect(doc.querySelector('[data-obs="9"]')).not.toBeNull();
    expect(doc.querySelector("[data-no-link]")!.textContent).toBe("Ligação de reserva disponível em breve.");
    expect(doc.textContent).toContain("Encontrado por um viajante a 11/10/2026");
  });

  it("refuses a booking link that is not https (cta.ts)", () => {
    const rows = [row(9, "BCN", 50, "2026-11-27", "2026-11-29", 0, "http://example.com/x")];
    expect(() => resultsHtml(explore(rows, NO_FILTERS, PONTES), places)).toThrow(/not https/);
  });
});

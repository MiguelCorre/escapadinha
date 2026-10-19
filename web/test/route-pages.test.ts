// Route pages (/voos/<origem>-<destino>/), origin pages (/partidas/<origem>/) and destination hubs
// (/destinos/<destino>/), built from the committed fixtures (#14, D30). Expected values are read off
// the fixture JSON by hand: LIS-PAR has a month without enough data (October) and two typical lows
// (102 € in November, 101,50 € in December); LIS-FNC has the live promotion 8 (obs 7226, also a
// low-price row) and two other low prices (7224, 7222); Paris is reached from LIS, OPO and FAO.
import { describe, expect, it } from "vitest";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { builtPages, page, text } from "./html";

const data = loadSiteData(FIXTURES_DIR);
const DISCLOSURE = "Publicidade: os botões de reserva são links de afiliado.";

describe("page set", () => {
  it("has a page at every route, origin and destination path of the contract", () => {
    const built = new Set(builtPages());
    const wanted = [
      ...data.routes.routes.map((r) => r.path),
      ...data.origins.origins.map((o) => o.path),
      ...data.destinations.destinations.map((d) => d.path),
      "/partidas/", "/destinos/",
    ];
    for (const path of wanted) expect(built.has(path), path).toBe(true);
    expect(data.routes.routes.map((r) => r.path)).toContain("/voos/lisboa-paris/");   // today's URLs
  });

  it("links every route page from its origin page and its destination hub", () => {
    for (const r of data.routes.routes) {
      const origin = data.origins.origins.find((o) => o.iata === r.origin)!;
      const dest = data.destinations.destinations.find((d) => d.code === r.destination)!;
      expect(page(origin.path).querySelector(`main a[href="${r.path}"]`), `${origin.path} -> ${r.path}`).not.toBeNull();
      expect(page(dest.path).querySelector(`main a[href="${r.path}"]`), `${dest.path} -> ${r.path}`).not.toBeNull();
    }
  });

  it("links the origins and destinations from the index pages, and the index from the nav", () => {
    for (const o of data.origins.origins) expect(page("/partidas/").querySelector(`main a[href="${o.path}"]`), o.path).not.toBeNull();
    for (const d of data.destinations.destinations) expect(page("/destinos/").querySelector(`main a[href="${d.path}"]`), d.path).not.toBeNull();
    expect(page("/").querySelector('header nav a[href="/destinos/"]')).not.toBeNull();
  });

  it("are indexable", () => {
    for (const path of ["/voos/lisboa-paris/", "/partidas/lisboa/", "/destinos/paris/", "/destinos/", "/partidas/"]) {
      expect(page(path).querySelector('meta[name="robots"]'), path).toBeNull();
    }
  });
});

describe("route page", () => {
  const doc = () => page("/voos/lisboa-paris/");

  it("names the route and links to the origin page and the destination hub", () => {
    expect(text(doc().querySelector("h1")!)).toBe("Voos de Lisboa para Paris");
    expect(doc().querySelector('main a[href="/partidas/lisboa/"]')).not.toBeNull();
    expect(doc().querySelector('main a[href="/destinos/paris/"]')).not.toBeNull();
  });

  it("shows the typical low per month, and says so when a month has too few days", () => {
    const table = doc().querySelector("[data-months]")!;
    expect(table.getAttribute("data-route")).toBe("LIS-PAR");
    const rows = table.querySelectorAll("tbody tr").map((tr) => text(tr));
    expect(rows).toHaveLength(3);
    expect(rows[0]).toContain("outubro de 2026");
    expect(rows[0]).toContain("ainda sem dados");
    expect(rows[0]).toContain("1 de 7 dias");          // meta.detector.min_baseline_days (D40)
    expect(rows[0]).not.toMatch(/€/);
    // Which days count (D40): the fixtures' meta.detector has min_dates_per_day (added by hand).
    expect(text(doc().querySelector("main")!)).toContain(
      "Precisamos de pelo menos 7 dias de dados num mês, contando só os dias com preços para 2 ou mais "
      + "datas de partida, antes de dizer o que é habitual.");
    expect(rows[1]).toContain("novembro de 2026");
    expect(rows[1]).toContain("102 €");
    expect(rows[2]).toContain("101,50 €");
  });

  it("has a calendar of the cheapest found prices, each day traced to its observation", () => {
    const calendar = doc().querySelector("[data-calendar]")!;
    const r = data.routes.routes.find((x) => x.key === "LIS-PAR")!;
    const cells = calendar.querySelectorAll("[data-obs]");
    expect(cells.map((c) => Number(c.getAttribute("data-obs"))).sort()).toEqual(r.calendar.map((c) => c.obs).sort());
    expect(cells.length).toBe(10);
    expect(calendar.querySelectorAll("caption").map((c) => text(c))).toContain("novembro de 2026");
  });
  // The link to the city's itinerary (#17) is tested with the content pages (content-pages.test.ts).
});

describe("route page with a live promotion and low prices", () => {
  const doc = () => page("/voos/lisboa-madeira/");

  it("shows the live promotion, then the other low prices (not its own offer again)", () => {
    expect(doc().querySelector('main [data-deal="8"] a[href="/promos/8-lisboa-madeira/"]')).not.toBeNull();
    const lows = doc().querySelectorAll("[data-low-prices] li[data-obs]").map((li) => li.getAttribute("data-obs"));
    expect(lows.sort()).toEqual(["7222", "7224"]);
  });

  it("gives each low price its found-on date, our first sight, the typical low and a tracked link", () => {
    const li = doc().querySelector('[data-low-prices] li[data-obs="7222"]')!;
    const body = text(li);
    expect(body).toContain("60 €");
    expect(body).toContain("Encontrado por um viajante a 13/10/2026");
    expect(body).toContain("Mínimo habitual em outubro: 102 €");
    expect(body).toContain("visto por nós a 13/10/2026 às 18:16");      // 17:16Z
    expect(text(li.querySelector('[data-route="LIS-FNC"]')!)).toBe("102 €");
    const link = li.querySelector('a[rel~="sponsored"]')!;
    expect(link.getAttribute("href")).toBe("https://example.com/parceiro/site-low-7222");
    expect(link.getAttribute("rel")).toBe("sponsored nofollow noopener");
    expect(text(link.closest("[data-cta]")!)).toContain(DISCLOSURE);
  });
});

describe("origin page", () => {
  const doc = () => page("/partidas/lisboa/");

  it("lists every destination from the origin with its cheapest found price", () => {
    expect(text(doc().querySelector("h1")!)).toBe("Voos desde Lisboa");
    const mine = data.routes.routes.filter((r) => r.origin === "LIS");
    for (const r of mine) {
      const item = doc().querySelector(`main li[data-route="${r.key}"]`)!;
      expect(item, r.key).not.toBeNull();
      if (r.cheapest) expect(item.querySelector(`[data-obs="${r.cheapest.obs}"]`), r.key).not.toBeNull();
    }
    const bcn = doc().querySelector('main li[data-route="LIS-BCN"]')!;
    expect(text(bcn)).toContain("Barcelona");
    expect(text(bcn)).toContain("51 €");
  });
});

describe("destination hub", () => {
  const doc = () => page("/destinos/paris/");

  it("lists every Portuguese origin with a route there, with its route page and best months", () => {
    expect(text(doc().querySelector("h1")!)).toBe("Paris");
    const lis = doc().querySelector('main [data-origin="LIS"]')!;
    expect(lis.querySelector('a[href="/voos/lisboa-paris/"]')).not.toBeNull();
    expect(lis.querySelector('a[href="/partidas/lisboa/"]')).not.toBeNull();
    const best = lis.querySelector("[data-best-months]")!;
    expect(best.getAttribute("data-route")).toBe("LIS-PAR");
    expect(text(best)).toMatch(/dezembro de 2026.*101,50 €.*novembro de 2026.*102 €/);
    const fao = doc().querySelector('main [data-origin="FAO"]')!;
    expect(text(fao)).toContain("Ainda sem dados suficientes");
    // By the cheapest price found now (FAO 69 €, OPO 70 €, LIS 92 €), then demand (D45); the
    // fixtures carry no demand, so ties would keep the contract's origin order.
    expect(doc().querySelectorAll("main [data-origin]").map((e) => e.getAttribute("data-origin")))
      .toEqual(["FAO", "OPO", "LIS"]);
  });
});

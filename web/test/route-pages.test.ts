// Route pages (/voos/<origem>-<destino>/), origin pages (/partidas/<origem>/) and destination hubs
// (/destinos/<destino>/), built from the committed fixtures (#14, D30). Expected values are read off
// the fixture JSON by hand: LIS-PAR has months without enough data (October, January to March)
// and two typical lows (96 € in November, 106 € in December); OPO-MIL has the live promotion 412
// (obs 71428, also a low-price row), one other low price (73602) and an expired promotion (283);
// OPO-PAR has the live promotion 408 at /promos/405-porto-paris/, whose five expired dates (413,
// 410, 407, 406, 405) belong to it (D53), and an expired promotion of its own (282); Paris is
// reached from LIS and OPO, London only from FAO, which has no typical low there yet.
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

describe("price verdict on route pages (D58)", () => {
  it("judges the cheapest offer against its departure month, naming the typical low on data-route", () => {
    // LIS-PAR: 88 € departing in November, typical low 96 € (high confidence): between the bands.
    const v = page("/voos/lisboa-paris/").querySelector("[data-verdict]")!;
    expect(v.getAttribute("data-verdict")).toBe("habitual");
    expect(text(v)).toBe("Preço habitual para novembro · mínimo habitual 96 €, comparado com o mínimo habitual que medimos nesta rota para esse mês");
    expect(text(v.querySelector('[data-route="LIS-PAR"]')!)).toBe("96 €");
    // LIS-FNC: 40 € in December against 55,50 € (medium): the low-price rule.
    const low = page("/voos/lisboa-madeira/").querySelector("[data-verdict]")!;
    expect(low.getAttribute("data-verdict")).toBe("baixo");
    expect(text(low)).toContain("Preço baixo para dezembro · mínimo habitual 55,50 €");
  });

  it("says nothing when the departure month has no mature typical low", () => {
    // OPO-MIL: 47 € departing in January 2027, a month with 2 days of data.
    expect(page("/voos/porto-milao/").querySelector("[data-verdict]")).toBeNull();
    expect(text(page("/voos/porto-milao/").querySelector("main")!)).not.toMatch(/Preço (baixo|habitual|alto) para/);
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
    expect(rows).toHaveLength(6);
    expect(rows[0]).toContain("outubro de 2026");
    expect(rows[0]).toContain("ainda sem dados");
    expect(rows[0]).toContain("5 de 7 dias");          // meta.detector.min_baseline_days (D40)
    expect(rows[0]).not.toMatch(/€/);
    // Which days count (D40): the fixtures' meta.detector has min_dates_per_day.
    expect(text(doc().querySelector("main")!)).toContain(
      "Precisamos de pelo menos 7 dias de dados num mês, contando só os dias com preços para 2 ou mais "
      + "datas de partida, antes de dizer o que é habitual.");
    expect(rows[1]).toContain("novembro de 2026");
    expect(rows[1]).toContain("96 €");
    expect(rows[2]).toContain("106 €");
    expect(rows[3]).toContain("janeiro de 2027");
    expect(rows[3]).toContain("2 de 7 dias");
  });

  it("has a calendar of the cheapest found prices, each day traced to its observation", () => {
    const calendar = doc().querySelector("[data-calendar]")!;
    const r = data.routes.routes.find((x) => x.key === "LIS-PAR")!;
    const cells = calendar.querySelectorAll("[data-obs]");
    expect(cells.map((c) => Number(c.getAttribute("data-obs"))).sort()).toEqual(r.calendar.map((c) => c.obs).sort());
    expect(cells.length).toBe(34);
    expect(calendar.querySelectorAll("caption").map((c) => text(c))).toContain("novembro de 2026");
  });
  // The link to the city's itinerary (#17) is tested with the content pages (content-pages.test.ts).
});

describe("route page with a live promotion and low prices", () => {
  const doc = () => page("/voos/porto-milao/");

  it("shows the live promotion, then the other low prices (not its own offer again)", () => {
    expect(doc().querySelector('main [data-deal="412"] a[href="/promos/412-porto-milao/"]')).not.toBeNull();
    const lows = doc().querySelectorAll("[data-low-prices] li[data-obs]").map((li) => li.getAttribute("data-obs"));
    expect(lows).toEqual(["73602"]);
  });

  it("gives each low price its found-on date, our first sight, the typical low and a tracked link", () => {
    const li = doc().querySelector('[data-low-prices] li[data-obs="73602"]')!;
    const body = text(li);
    expect(body).toContain("85 €");
    expect(body).toContain("Encontrado por um viajante a 02/11/2026 às 06:06");   // D59: found_at 06:06:17Z
    expect(li.querySelector('[data-found-at="2026-11-02T06:06Z"]')).not.toBeNull();
    expect(body).toContain("Mínimo habitual em fevereiro: 101 €");
    expect(body).toContain("visto por nós a 02/11/2026 às 11:18");      // 11:18Z: Lisbon is UTC in November
    expect(text(li.querySelector('[data-route="OPO-MIL"]')!)).toBe("101 €");
    const link = li.querySelector('a[rel~="sponsored"]')!;
    expect(link.getAttribute("href")).toBe("https://example.com/parceiro/site-low-73602");
    expect(link.getAttribute("rel")).toBe("sponsored nofollow noopener");
    expect(text(link.closest("[data-cta]")!)).toContain(DISCLOSURE);
  });
});

describe("route page with a promotion of several dates (D53)", () => {
  const doc = () => page("/voos/porto-paris/");

  it("shows one card per promotion: the live lead, never its expired dates", () => {
    const cards = doc().querySelectorAll("main article[data-deal]");
    expect(cards.map((c) => c.getAttribute("data-deal"))).toEqual(["408", "282"]);
    expect(cards[0].querySelector('a[href="/promos/405-porto-paris/"]')).not.toBeNull();
    expect(text(cards[1])).toContain("Expirada");
    const group = data.promotions.promotions.filter((p) => p.promotion?.id === data.promotions.promotions
      .find((x) => x.id === 408)!.promotion!.id);
    expect(group.map((p) => p.id).sort()).toEqual([405, 406, 407, 408, 410, 413]);
  });

  it("leaves the live date's own offer out of the low prices", () => {
    const lows = doc().querySelectorAll("[data-low-prices] li[data-obs]").map((li) => li.getAttribute("data-obs"));
    expect(lows).toEqual(["52426", "67832", "67795"]);
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
    expect(text(bcn)).toContain("49 €");
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
    expect(text(best)).toMatch(/novembro de 2026.*96 €.*dezembro de 2026.*106 €/);
    // By the cheapest price found now (OPO 49 €, LIS 88 €), then demand (D45), then the
    // contract's origin order.
    expect(doc().querySelectorAll("main [data-origin]").map((e) => e.getAttribute("data-origin")))
      .toEqual(["OPO", "LIS"]);
  });

  it("says when an origin has no typical low there yet", () => {
    const fao = page("/destinos/londres/").querySelector('main [data-origin="FAO"]')!;
    expect(text(fao)).toContain("Ainda sem dados suficientes");
  });
});

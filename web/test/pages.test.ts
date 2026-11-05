// The site built from the committed fixtures: what a visitor sees on the home page and on a live
// and an expired promotion page. Expected values are read off the fixture JSON by hand
// (promotion 412 = live OPO-MIL, promotion 397 = expired LIS-PAR; base_url pontonomada.pt; the
// data's times are in November, when Lisbon time is UTC).
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fixtureImages, placeholderSvg } from "../src/lib/fixture-images";
import { pagePromotions } from "../src/lib/promotion";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { brokenLinks, builtPages, distDir, page, text } from "./html";

const BASE = "https://pontonomada.pt";
const LIVE = "/promos/412-porto-milao/";
const EXPIRED = "/promos/397-lisboa-paris/";
const SITE_DISCLOSURE = "Publicidade: os botões de reserva são links de afiliado.";

describe("built pages", () => {
  it("are the home page, one page per promotion, the explorer and the ponte pages", () => {
    const data = loadSiteData(FIXTURES_DIR);
    const promos = builtPages().filter((p) => p.startsWith("/promos/"));
    // One page per promotion (D53): the dates grouped under another item's page have none.
    expect(promos.sort()).toEqual(pagePromotions(data).map((p) => p.path).sort());
    expect(promos).toEqual(expect.arrayContaining([LIVE, EXPIRED]));
    expect(promos.length).toBeLessThan(data.promotions.promotions.length);
    const pontes = data.pontes.pontes.flatMap((p) => p.origins.map((o) => o.path));
    expect(builtPages().filter((p) => p.startsWith("/pontes/")).sort()).toEqual(pontes.sort());
    expect(builtPages()).toEqual(expect.arrayContaining(["/", "/404.html", "/explorar/"]));
  });

  it("are in European Portuguese with a canonical URL on the data's base URL", () => {
    for (const path of builtPages()) {
      const doc = page(path);
      expect(doc.querySelector("html")!.getAttribute("lang"), path).toBe("pt-PT");
      if (path.endsWith(".html")) continue;
      expect(doc.querySelector('link[rel="canonical"]')!.getAttribute("href"), path).toBe(BASE + path);
      expect(doc.querySelector('meta[property="og:image"]')!.getAttribute("content"), path)
        .toMatch(/^https:\/\/pontonomada\.pt\/.+\.(png|jpg)$/);
    }
  });

  it("are marked as built from fixture data, so a deploy can refuse them", () => {
    for (const path of builtPages()) {
      expect(page(path).querySelector("html")!.getAttribute("data-fixture"), path).toBe("true");
    }
  });

  it("have stand-in promotion images (fixture build only), so Lighthouse measures the LCP image", () => {
    const data = loadSiteData(FIXTURES_DIR);
    const paths = data.promotions.promotions.flatMap((p) => [p.images!.thumb!, p.images!.og!, ...p.images!.slides]);
    expect(paths.length).toBeGreaterThan(0);
    for (const src of paths) expect(existsSync(join(distDir(), src)), src).toBe(true);
    expect(fixtureImages({ ...data, meta: { ...data.meta, fixture: false } })).toEqual([]);
    const slide = fixtureImages(data).find((i) => i.name === "slide_01")!;
    expect([slide.width, slide.height]).toEqual([1080, 1350]);
    expect(placeholderSvg(slide)).toContain('width="1080" height="1350"');
  });

  it("only link to pages and files that exist (internal links resolve)", () => {
    expect(brokenLinks(distDir())).toEqual([]);
    // The check looked at the new page types' links too (route, origin, destination pages).
    const links = page("/voos/lisboa-paris/").querySelectorAll("main a[href^='/']").length;
    expect(links).toBeGreaterThanOrEqual(4);
  });
});

describe("home page", () => {
  const home = () => page("/");

  it("features the live promotion with its price block", () => {
    const card = home().querySelector(`[data-deal="412"]`)!;
    expect(card.querySelector(`a[href="${LIVE}"]`)).not.toBeNull();
    expect(text(card)).toContain("Porto → Milão");
    expect(text(card.querySelector('[data-obs="71428"]')!)).toBe("58 €");
    expect(text(card)).toContain("−43%");
    expect(text(card)).toContain("sex, 12 fev → seg, 15 fev · 3 noites");
    expect(text(card)).toContain("01/11/2026");
    expect(text(card.querySelector("[data-flight]")!)).toBe("Wizz Air · só bagagem de mão");   // known (D43)
  });

  it("lists the recently expired promotion as expired, without its booking link", () => {
    const card = home().querySelector(`[data-deal="397"]`)!;
    expect(card.querySelector(`a[href="${EXPIRED}"]`)).not.toBeNull();
    expect(text(card)).toContain("Lisboa → Paris (Beauvais)");
    expect(text(card)).toContain("Expirada");
    expect(text(card.querySelector("[data-flight]")!)).toBe("Ryanair");       // baggage unknown: no line (D43)
    expect(home().querySelector('a[href^="https://example.com/parceiro/site-deal-397"]')).toBeNull();
  });

  it("is indexable", () => {
    expect(home().querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("live promotion page", () => {
  const doc = () => page(LIVE);

  it("names the arrival city in the headline (no remote airport here)", () => {
    expect(text(doc().querySelector("h1")!)).toBe("Porto → Milão");
  });

  it("carries the price verdict against the route's month (D58), the typical low on data-route", () => {
    // 58 € departing in February 2027; OPO-MIL's February typical low is 101 € (high confidence).
    const v = doc().querySelector("[data-verdict]")!;
    expect(v.getAttribute("data-verdict")).toBe("baixo");
    expect(text(v)).toContain("Preço baixo para fevereiro · mínimo habitual 101 €, comparado com");
    expect(text(v.querySelector('[data-route="OPO-MIL"]')!)).toBe("101 €");
    expect(page(EXPIRED).querySelector("[data-verdict]")).toBeNull();
  });

  it("shows price, discount, dates and who found the price when", () => {
    const body = text(doc().querySelector("main")!);
    expect(text(doc().querySelector('main [data-obs="71428"]')!)).toBe("58 €");
    expect(text(doc().querySelector('main [data-obs="71428"] .price-sign')!)).toBe("€");   // raised sign
    expect(body).toContain("−43%");
    expect(doc().querySelector('meta[name="description"]')!.getAttribute("content"))
      .toMatch(/ida e volta, 43% abaixo do habitual em fevereiro/);
    expect(body).toContain("abaixo do habitual");
    expect(body).toContain("sex, 12 fev → seg, 15 fev · 3 noites");
    // D59: the exact Lisbon hour (obs 71428, found_at 21:53:44Z, Lisbon = UTC in November) with
    // the instant on data-found-at for the browser's "(há x h)"; the build writes no relative time.
    expect(body).toContain("Encontrado por um viajante a 01/11/2026 às 21:53");
    const found = doc().querySelector('main [data-found-at="2026-11-01T21:53:44Z"]')!;
    expect(text(found)).toBe("01/11/2026 às 21:53");
    expect(body).toContain("o preço foi encontrado a 01/11/2026 às 21:53 e verificado por nós a");
    expect(body).toContain("02/11/2026 às 16:49"); // checked_at 16:49Z: Lisbon time is UTC in November
    expect(body).toContain("101 €"); // the typical low it was measured against
    expect(body).toContain("Wizz Air");
  });

  it("lists what other sources saw for the same trip (D47), each price on its observation", () => {
    const seen = ["74238", "74237"].map((obs) => doc().querySelector(`main [data-obs="${obs}"]`)!);
    expect(seen.map((e) => text(e))).toEqual(["74 €", "80 €"]);
    expect(seen.map((e) => text(e.parentNode!))).toEqual(["Kayak · 74 €", "Google Flights via Ryanair · 80 €"]);
  });

  it("leads with the one-line summary and lists routes, best months, publication and how to book (D46)", () => {
    const d = doc();
    const summary = d.querySelector("main [data-summary]")!;
    expect(text(summary)).toBe("Voos diretos por 58 € ida e volta, com a Wizz Air, só bagagem de mão.");
    expect(text(summary.querySelector('[data-obs="71428"]')!)).toBe("58\u00a0€");
    const body = text(d.querySelector("main")!);
    expect(body).toContain("Porto – Milão (MXP) – Porto");
    expect(body).toContain("dezembro de 2026, novembro de 2026 e fevereiro de 2027");   // cheapest typical low first
    expect(d.querySelector('main a[href="/voos/porto-milao/"]')).not.toBeNull();
    expect(body).toContain("02/11/2026 às 06:20");                                    // approved_at, Lisbon
    const steps = d.querySelectorAll("main #como-reservar ~ ol li");
    expect(steps.length).toBe(3);
    expect(text(steps[0])).toContain("abre a pesquisa do parceiro já com estas datas");
    expect(text(steps[2])).toContain("encontrado a 01/11/2026 às 21:53 e verificado por nós a 02/11/2026 às 16:49");
    // #79 (D56): the fixture's `outcomes` (36 approved, 28 % still bookable a day later), live only.
    expect(text(steps[2].querySelector("[data-outcomes]")!))
      .toBe("Das últimas 36 promoções que publicámos, 28% ainda estavam disponíveis 24 horas depois.");
    expect(page(EXPIRED).querySelector("[data-outcomes]")).toBeNull();
  });

  it("has one tracked booking button with the disclosure next to it", () => {
    const links = doc().querySelectorAll('a[rel~="sponsored"]');
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/parceiro/site-deal-412"]);
    expect(links[0].getAttribute("rel")).toContain("nofollow");
    expect(text(links[0].closest("[data-cta]")!)).toContain(SITE_DISCLOSURE);
  });

  it("is indexable and shares the promotion's own OG image", () => {
    expect(doc().querySelector('meta[name="robots"]')).toBeNull();
    expect(doc().querySelector('meta[property="og:image"]')!.getAttribute("content"))
      .toBe(`${BASE}/img/promos/412/og.jpg`);
  });
});

describe("expired promotion page", () => {
  const doc = () => page(EXPIRED);

  it("is noindex", () => {
    expect(doc().querySelector('meta[name="robots"]')!.getAttribute("content")).toBe("noindex");
  });

  it("names the remote arrival airport in the headline", () => {
    expect(text(doc().querySelector("h1")!)).toBe("Lisboa → Paris (Beauvais)");
  });

  it("has no booking steps and no price-led summary", () => {
    expect(page(EXPIRED).querySelector("#como-reservar")).toBeNull();
    expect(page(EXPIRED).querySelector("[data-summary]")).toBeNull();
  });

  it("has no booking button", () => {
    expect(doc().querySelectorAll('a[rel~="sponsored"]')).toHaveLength(0);
    expect(doc().querySelectorAll("[data-cta]")).toHaveLength(0);
  });

  it("says it expired and why, with the price the recheck saw traced to its observation", () => {
    const notice = doc().querySelector("[data-expired]")!;
    expect(text(notice)).toContain("Expirada");
    expect(text(notice)).toContain("o preço subiu para 67,98 €");
    expect(notice.getAttribute("data-obs")).toBe("52940");
  });

  it("keeps the old price, struck through", () => {
    const price = doc().querySelector("main [data-obs='37258']")!;
    expect(text(price)).toBe("66,98 €");
    expect(text(price.querySelector("s")!)).toBe("66,98");
  });
});

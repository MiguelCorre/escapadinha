// The site built from the committed fixtures: what a visitor sees on the home page and on a live
// and an expired promotion page. Expected values are read off the fixture JSON by hand
// (promotion 8 = live LIS-FNC, promotion 3 = expired LIS-PAR; base_url pontonomada.pt).
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fixtureImages, placeholderSvg } from "../src/lib/fixture-images";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { brokenLinks, builtPages, distDir, page, text } from "./html";

const BASE = "https://pontonomada.pt";
const LIVE = "/promos/8-lisboa-madeira/";
const EXPIRED = "/promos/3-lisboa-paris/";
const SITE_DISCLOSURE = "Publicidade: os botões de reserva são links de afiliado.";

describe("built pages", () => {
  it("are the home page, one page per promotion, the explorer and the ponte pages", () => {
    const promos = builtPages().filter((p) => p.startsWith("/promos/"));
    expect(promos.sort()).toEqual([EXPIRED, LIVE].sort());
    const pontes = loadSiteData(FIXTURES_DIR).pontes.pontes.flatMap((p) => p.origins.map((o) => o.path));
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
    const card = home().querySelector(`[data-deal="8"]`)!;
    expect(card.querySelector(`a[href="${LIVE}"]`)).not.toBeNull();
    expect(text(card)).toContain("Lisboa → Madeira");
    expect(text(card.querySelector('[data-obs="7226"]')!)).toBe("69 €");
    expect(text(card)).toContain("−32%");
    expect(text(card)).toContain("sáb, 31 out → ter, 3 nov · 3 noites");
    expect(text(card)).toContain("11/10/2026");
  });

  it("lists the recently expired promotion as expired, without its booking link", () => {
    const card = home().querySelector(`[data-deal="3"]`)!;
    expect(card.querySelector(`a[href="${EXPIRED}"]`)).not.toBeNull();
    expect(text(card)).toContain("Lisboa → Paris (Beauvais)");
    expect(text(card)).toContain("Expirada");
    expect(home().querySelector('a[href^="https://example.com/parceiro/site-deal-3"]')).toBeNull();
  });

  it("is indexable", () => {
    expect(home().querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("live promotion page", () => {
  const doc = () => page(LIVE);

  it("names the arrival city in the headline (no remote airport here)", () => {
    expect(text(doc().querySelector("h1")!)).toBe("Lisboa → Madeira");
  });

  it("shows price, discount, dates and who found the price when", () => {
    const body = text(doc().querySelector("main")!);
    expect(text(doc().querySelector('main [data-obs="7226"]')!)).toBe("69 €");
    expect(text(doc().querySelector('main [data-obs="7226"] .price-sign')!)).toBe("€");   // raised sign
    expect(body).toContain("−32%");
    expect(doc().querySelector('meta[name="description"]')!.getAttribute("content"))
      .toMatch(/ida e volta, 32% abaixo do habitual em outubro/);
    expect(body).toContain("abaixo do habitual");
    expect(body).toContain("sáb, 31 out → ter, 3 nov · 3 noites");
    expect(body).toContain("Encontrado por um viajante a 11/10/2026");
    expect(body).toContain("14/10/2026 às 10:01"); // checked_at 09:01Z in Lisbon time
    expect(body).toContain("102 €"); // the typical low it was measured against
    expect(body).toContain("Ryanair");
  });

  it("has one tracked booking button with the disclosure next to it", () => {
    const links = doc().querySelectorAll('a[rel~="sponsored"]');
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/parceiro/site-deal-8"]);
    expect(links[0].getAttribute("rel")).toContain("nofollow");
    expect(text(links[0].closest("[data-cta]")!)).toContain(SITE_DISCLOSURE);
  });

  it("is indexable and shares the promotion's own OG image", () => {
    expect(doc().querySelector('meta[name="robots"]')).toBeNull();
    expect(doc().querySelector('meta[property="og:image"]')!.getAttribute("content"))
      .toBe(`${BASE}/img/promos/8/og.jpg`);
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

  it("has no booking button", () => {
    expect(doc().querySelectorAll('a[rel~="sponsored"]')).toHaveLength(0);
    expect(doc().querySelectorAll("[data-cta]")).toHaveLength(0);
  });

  it("says it expired and why, with the price the recheck saw traced to its observation", () => {
    const notice = doc().querySelector("[data-expired]")!;
    expect(text(notice)).toContain("Expirada");
    expect(text(notice)).toContain("o preço subiu para 91 €");
    expect(notice.getAttribute("data-obs")).toBe("2347");
  });

  it("keeps the old price, struck through", () => {
    const price = doc().querySelector("main [data-obs='2792']")!;
    expect(text(price)).toBe("86 €");
    expect(text(price.querySelector("s")!)).toBe("86");
  });
});

// The site built from the committed fixtures: what a visitor sees on the home page and on a live
// and an expired promotion page. Expected values are read off the fixture JSON by hand
// (promotion 412 = live OPO-MIL, promotion 397 = expired LIS-PAR; base_url pontonomada.pt; the
// data's times are in November, when Lisbon time is UTC).
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fixtureImages, placeholderSvg } from "../src/lib/fixture-images";
import { expiredByRoute, expiredOnRoute, pagePromotions } from "../src/lib/promotion";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { brokenLinks, builtPages, distDir, page, text } from "./html";

const BASE = "https://pontonomada.pt";
const LIVE = "/promos/412-porto-milao/";
const EXPIRED = "/promos/397-lisboa-paris/";
const SITE_DISCLOSURE = "Publicidade: os botões de reserva são links de afiliado.";

describe("built pages", () => {
  it("are the home page, one page per promotion, the explorer and the ponte pages", () => {
    const data = loadSiteData(FIXTURES_DIR);
    const promos = builtPages().filter((p) => /^\/promos\/[^/]+\/$/.test(p));   // not /promos/ itself (D60)
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

  it("lists the expired promotions one per route, the most recent, with the route's count (D60)", () => {
    const data = loadSiteData(FIXTURES_DIR);
    const records = expiredByRoute(data);
    expect(records.length).toBeGreaterThan(1);
    expect(data.meta.home_expired_max).toBe(6);
    const cards = home().querySelectorAll("#titulo-expiradas ~ div [data-deal]");
    expect(cards.map((c) => Number(c.getAttribute("data-deal"))))
      .toEqual(records.slice(0, 6).map((r) => r.latest.id));
    expect(home().querySelector("[data-expired-routes]")!.getAttribute("data-expired-routes")).toBe(String(records.length));
    // LIS-PAR: 409 is the most recent of its three expired page promotions (404 is a grouped date
    // of 409's promotion, whose page is /promos/404-lisboa-paris/, D53); 397, a page of its own,
    // is not a card.
    const lisPar = records.find((r) => r.route === "LIS-PAR")!;
    expect([lisPar.latest.id, lisPar.count, lisPar.latest.path]).toEqual([409, 3, "/promos/404-lisboa-paris/"]);
    expect(home().querySelector(`[data-deal="397"]`)).toBeNull();
    const card = home().querySelector(`[data-deal="409"]`)!;
    expect(card.querySelector('a[href="/promos/404-lisboa-paris/"]')).not.toBeNull();
    expect(text(card)).toContain("Expirada");
    const more = card.querySelector("[data-more-on-route] a")!;
    expect(text(more)).toBe("+ 2 promoções nesta rota nos últimos 30 dias");
    expect(more.getAttribute("href")).toBe("/voos/lisboa-paris/");
    // A route with one expired promotion says nothing more; no booking link anywhere.
    const single = records.find((r) => r.count === 1)!;
    expect(home().querySelector(`[data-deal="${single.latest.id}"] [data-more-on-route]`)).toBeNull();
    expect(home().querySelector('a[href^="https://example.com/parceiro/site-deal-"]')).toBeNull();
    expect(home().querySelector('a[href="/promos/"]')).not.toBeNull();
  });

  it("is indexable", () => {
    expect(home().querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("/promos/, the record page (D60)", () => {
  const doc = () => page("/promos/");
  const data = loadSiteData(FIXTURES_DIR);

  it("lists every live promotion, then every expired one grouped by route, newest first", () => {
    const live = pagePromotions(data).filter((p) => p.live);
    const liveCards = doc().querySelectorAll("#ativas [data-deal]").map((c) => Number(c.getAttribute("data-deal")));
    expect(liveCards.sort()).toEqual(live.map((p) => p.id).sort());
    const records = expiredByRoute(data);
    const groups = doc().querySelectorAll("[data-route-group]");
    expect(groups.map((g) => g.getAttribute("data-route-group"))).toEqual(records.map((r) => r.route));
    for (const g of groups) {
      const ids = g.querySelectorAll("[data-deal]").map((c) => Number(c.getAttribute("data-deal")));
      expect(ids, g.getAttribute("data-route-group")!).toEqual(expiredOnRoute(data, g.getAttribute("data-route-group")!).map((p) => p.id));
      expect(ids.slice(1).every((id, i) => id < ids[i])).toBe(true);        // newest first
    }
    expect(doc().querySelectorAll("[data-deal]").length).toBe(pagePromotions(data).length);
    expect(text(doc().querySelector("h1")!)).toBe("Promoções recentes");
    expect(doc().querySelector('[data-route-group="LIS-PAR"] a[href="/voos/lisboa-paris/"]')).not.toBeNull();
  });

  it("has no booking link on an expired card and is indexed while a promotion is live", () => {
    expect(doc().querySelector('a[href^="https://example.com/parceiro/site-deal-"]')).toBeNull();
    expect(doc().querySelector('meta[name="robots"]')).toBeNull();
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

  it("has its tracked booking button with the disclosure next to it, on phones right under the price (D66)", () => {
    const links = doc().querySelectorAll('a[rel~="sponsored"]');
    // The phone's early button under the price block, then the one under the details (D66).
    expect(links.map((a) => a.getAttribute("href"))).toEqual(Array(2).fill("https://example.com/parceiro/site-deal-412"));
    for (const link of links) {
      expect(link.getAttribute("rel")).toContain("nofollow");
      expect(text(link.closest("[data-cta]")!)).toContain(SITE_DISCLOSURE);
    }
    const early = doc().querySelector("[data-cta-early]")!;
    expect(early.classList.contains("md:hidden")).toBe(true);           // phones only
    expect(early.querySelector('a[rel~="sponsored"]')!.getAttribute("href")).toBe("https://example.com/parceiro/site-deal-412");
    expect(text(early)).toContain(SITE_DISCLOSURE);
    // Order in the page: price block, early button, the details table, the lower button.
    const html = doc().querySelector("article")!.innerHTML;
    const at = (needle: string) => html.indexOf(needle);
    expect(at("price-block")).toBeGreaterThan(-1);
    expect(at("price-block")).toBeLessThan(at("data-cta-early"));
    expect(at("data-cta-early")).toBeLessThan(at("<dl"));
    expect(at("<dl")).toBeLessThan(html.lastIndexOf("data-cta"));
    expect(page(EXPIRED).querySelector("[data-cta-early]")).toBeNull();   // expired: no button
    expect(page(EXPIRED).querySelector('a[rel~="sponsored"]')).toBeNull();
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

describe("header navigation (D66)", () => {
  it("makes every link a 44 px tap target on phones and leaves the desktop look alone", () => {
    const links = page("/").querySelectorAll('nav[aria-label="Principal"] a');
    expect(links.length).toBe(3);
    for (const a of links) expect(a.classList.contains("nav-link")).toBe(true);
    const css = page("/").querySelectorAll("style").map((s) => s.textContent).join("\n");
    expect(css).toMatch(/\.nav-link\{[^}]*min-height:44px/);
  });
});

// The site built from the committed fixtures: what a visitor sees on the home page and on a live
// and an expired promotion page. Expected values are read off the fixture JSON by hand
// (promotion 3 = live LIS-PAR, promotion 2 = expired OPO-PAR; base_url ondestaanocas.pages.dev).
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { builtPages, distDir, page, text } from "./html";

const BASE = "https://ondestaanocas.pages.dev";
const LIVE = "/promos/3-lisboa-paris/";
const EXPIRED = "/promos/2-porto-paris/";
const SITE_DISCLOSURE = "Publicidade: os botões de reserva são links de afiliado.";

describe("built pages", () => {
  it("are the home page and one page per promotion in the contract", () => {
    expect(builtPages().sort()).toEqual(["/", "/404.html", EXPIRED, LIVE].sort());
  });

  it("are in European Portuguese with a canonical URL on the data's base URL", () => {
    for (const path of builtPages()) {
      const doc = page(path);
      expect(doc.querySelector("html")!.getAttribute("lang"), path).toBe("pt-PT");
      if (path.endsWith(".html")) continue;
      expect(doc.querySelector('link[rel="canonical"]')!.getAttribute("href"), path).toBe(BASE + path);
      expect(doc.querySelector('meta[property="og:image"]')!.getAttribute("content"), path)
        .toMatch(/^https:\/\/ondestaanocas\.pages\.dev\/.+\.(png|jpg)$/);
    }
  });

  it("are marked as built from fixture data, so a deploy can refuse them", () => {
    for (const path of builtPages()) {
      expect(page(path).querySelector("html")!.getAttribute("data-fixture"), path).toBe("true");
    }
  });

  it("only link to pages and files that exist", () => {
    for (const path of builtPages()) {
      for (const a of page(path).querySelectorAll("a[href^='/'], link[href^='/'], img[src^='/']")) {
        const target = (a.getAttribute("href") ?? a.getAttribute("src"))!.split("#")[0];
        if (target.startsWith("/img/promos/")) continue; // slides come with the pipeline's output
        const file = target.endsWith("/") ? join(target, "index.html") : target;
        expect(existsSync(join(distDir(), file)), `${path} links to ${target}`).toBe(true);
      }
    }
  });
});

describe("home page", () => {
  const home = () => page("/");

  it("features the live promotion with its price block", () => {
    const card = home().querySelector(`[data-deal="3"]`)!;
    expect(card.querySelector(`a[href="${LIVE}"]`)).not.toBeNull();
    expect(text(card)).toContain("Lisboa → Paris (Beauvais)");
    expect(text(card.querySelector('[data-obs="2792"]')!)).toBe("86 €");
    expect(text(card)).toContain("−44%");
    expect(text(card)).toContain("qua, 9 dez → sex, 11 dez · 2 noites");
    expect(text(card)).toContain("12/10/2026");
  });

  it("lists the recently expired promotion as expired, without its booking link", () => {
    const card = home().querySelector(`[data-deal="2"]`)!;
    expect(card.querySelector(`a[href="${EXPIRED}"]`)).not.toBeNull();
    expect(text(card)).toContain("Expirada");
    expect(home().querySelector('a[href^="https://example.com/parceiro/site-deal-2"]')).toBeNull();
  });

  it("is indexable", () => {
    expect(home().querySelector('meta[name="robots"]')).toBeNull();
  });
});

describe("live promotion page", () => {
  const doc = () => page(LIVE);

  it("names the remote arrival airport in the headline", () => {
    expect(text(doc().querySelector("h1")!)).toBe("Lisboa → Paris (Beauvais)");
  });

  it("shows price, discount, dates and who found the price when", () => {
    const body = text(doc().querySelector("main")!);
    expect(text(doc().querySelector('main [data-obs="2792"]')!)).toBe("86 €");
    expect(body).toContain("−44%");
    expect(body).toContain("abaixo do habitual");
    expect(body).toContain("qua, 9 dez → sex, 11 dez · 2 noites");
    expect(body).toContain("Encontrado por um viajante a 12/10/2026");
    expect(body).toContain("12/10/2026 às 22:17"); // checked_at 21:17Z in Lisbon time
    expect(body).toContain("153,50 €"); // the typical low it was measured against
    expect(body).toContain("Ryanair");
  });

  it("has one tracked booking button with the disclosure next to it", () => {
    const links = doc().querySelectorAll('a[rel~="sponsored"]');
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://example.com/parceiro/site-deal-3"]);
    expect(links[0].getAttribute("rel")).toContain("nofollow");
    expect(text(links[0].closest("[data-cta]")!)).toContain(SITE_DISCLOSURE);
  });

  it("is indexable and shares the promotion's own OG image", () => {
    expect(doc().querySelector('meta[name="robots"]')).toBeNull();
    expect(doc().querySelector('meta[property="og:image"]')!.getAttribute("content"))
      .toBe(`${BASE}/img/promos/3/og.jpg`);
  });
});

describe("expired promotion page", () => {
  const doc = () => page(EXPIRED);

  it("is noindex", () => {
    expect(doc().querySelector('meta[name="robots"]')!.getAttribute("content")).toBe("noindex");
  });

  it("has no booking button", () => {
    expect(doc().querySelectorAll('a[rel~="sponsored"]')).toHaveLength(0);
    expect(doc().querySelectorAll("[data-cta]")).toHaveLength(0);
  });

  it("says it expired and why, with the price the recheck saw traced to its observation", () => {
    const notice = doc().querySelector("[data-expired]")!;
    expect(text(notice)).toContain("Expirada");
    expect(text(notice)).toContain("o preço subiu para 70 €");
    expect(notice.getAttribute("data-obs")).toBe("3040");
  });

  it("keeps the old price, struck through", () => {
    const price = doc().querySelector("main [data-obs='2598']")!;
    expect(text(price)).toBe("60 €");
    expect(text(price.querySelector("s")!)).toBe("60");
  });
});

// SEO on the fixture build (D34): canonical, OpenGraph and Twitter tags on every page, sitemap.xml
// with exactly the indexable pages, robots.txt pointing at it, JSON-LD that validates (test/jsonld.ts)
// with prices traced to the contract, the About and Privacy pages, and nothing third-party: no
// analytics beacon and no search widget in a fixture build (both unconfigured), no cookies.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { eur } from "../src/lib/format";
import { SEARCH_BUTTON } from "../src/lib/search-widget";
import { builtPages, distDir, page, text } from "./html";
import { jsonLd, jsonLdErrors } from "./jsonld";
import { traceableAmounts } from "./trace";

const BASE = "https://pontonomada.pt";
const LIVE = "/promos/8-lisboa-madeira/";
const EXPIRED = "/promos/3-lisboa-paris/";
const ITINERARY = "/roteiros/paris-em-3-dias/";
const TIP = "/dicas/dica-de-teste/";
const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const data = loadSiteData(FIXTURES_DIR);

const htmlPages = () => builtPages().filter((p) => p.endsWith("/"));
const noindex = (path: string) => page(path).querySelector('meta[name="robots"]')?.getAttribute("content")?.includes("noindex") ?? false;
const meta = (path: string, attr: string, key: string) =>
  page(path).querySelector(`meta[${attr}="${key}"]`)?.getAttribute("content");

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : [join(dir, e.name)]);
}

function sitemapUrls(): string[] {
  const xml = readFileSync(join(distDir(), "sitemap.xml"), "utf8");
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
}

describe("head tags", () => {
  it("every page has its canonical URL, OpenGraph and Twitter tags", () => {
    for (const path of htmlPages()) {
      const doc = page(path);
      const title = doc.querySelector("title")!.textContent;
      expect(doc.querySelector('link[rel="canonical"]')!.getAttribute("href"), path).toBe(BASE + path);
      expect(meta(path, "property", "og:url"), path).toBe(BASE + path);
      expect(meta(path, "property", "og:title"), path).toBe(title);
      expect(meta(path, "property", "og:description"), path).toBeTruthy();
      expect(meta(path, "property", "og:image"), path).toMatch(/^https:\/\/pontonomada\.pt\/.+\.(png|jpg)$/);
      expect(meta(path, "property", "og:image:alt"), path).toBeTruthy();
      expect(meta(path, "name", "twitter:card"), path).toBe("summary_large_image");
      expect(meta(path, "name", "twitter:title"), path).toBe(title);
      expect(meta(path, "name", "twitter:description"), path).toBe(meta(path, "property", "og:description"));
      expect(meta(path, "name", "twitter:image"), path).toBe(meta(path, "property", "og:image"));
    }
  });

  it("articles are og:type article, everything else website", () => {
    expect(meta(ITINERARY, "property", "og:type")).toBe("article");
    expect(meta(TIP, "property", "og:type")).toBe("article");
    expect(meta("/", "property", "og:type")).toBe("website");
    expect(meta(LIVE, "property", "og:type")).toBe("website");
  });
});

describe("sitemap and robots", () => {
  it("the sitemap lists exactly the indexable pages, at their canonical URLs", () => {
    const indexable = htmlPages().filter((p) => !noindex(p)).map((p) => BASE + p).sort();
    expect(sitemapUrls().sort()).toEqual(indexable);
    expect(new Set(sitemapUrls()).size).toBe(sitemapUrls().length);
  });

  it("leaves out expired promotions, empty or past pontes, the 404 page and drafts", () => {
    const urls = sitemapUrls();
    expect(urls).toContain(BASE + LIVE);
    expect(urls).not.toContain(BASE + EXPIRED);
    expect(urls.filter((u) => u.includes("/pontes/"))).toEqual([]);   // no fixture trip fits a ponte (D31)
    expect(urls.some((u) => u.includes("404"))).toBe(false);
    expect(urls.some((u) => u.includes("rascunho"))).toBe(false);
    for (const p of ["/", "/explorar/", "/destinos/paris/", "/voos/lisboa-paris/", "/partidas/lisboa/",
      ITINERARY, TIP, "/privacidade/", "/sobre/"]) {
      expect(urls, p).toContain(BASE + p);
    }
  });

  it("is valid sitemap XML", () => {
    const xml = readFileSync(join(distDir(), "sitemap.xml"), "utf8");
    expect(xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml.trimEnd().endsWith("</urlset>")).toBe(true);
  });

  it("robots.txt allows crawling and points at the sitemap on the base URL", () => {
    const robots = readFileSync(join(distDir(), "robots.txt"), "utf8");
    expect(robots).toContain("User-agent: *\nAllow: /");
    expect(robots).toContain(`Sitemap: ${BASE}/sitemap.xml`);
  });
});

describe("structured data (JSON-LD)", () => {
  it("every block on every page validates against its type's schema", () => {
    const problems: string[] = [];
    let blocks = 0;
    for (const path of htmlPages()) {
      for (const block of jsonLd(page(path))) {
        blocks++;
        problems.push(...jsonLdErrors(block).map((e) => `${path}: ${e}`));
      }
    }
    expect(problems).toEqual([]);
    expect(blocks).toBeGreaterThan(10);
  });

  it("the validator rejects an invented property, a wrong type and a string price", () => {
    expect(jsonLdErrors({ type: "Recipe", data: {} })).not.toEqual([]);
    const crumbs = { "@context": "https://schema.org", "@type": "BreadcrumbList", itemListElement: [
      { "@type": "ListItem", position: 1, name: "A", item: `${BASE}/a/` },
      { "@type": "ListItem", position: 2, name: "B", item: `${BASE}/b/` }] };
    expect(jsonLdErrors({ type: "BreadcrumbList", data: crumbs })).toEqual([]);
    expect(jsonLdErrors({ type: "BreadcrumbList", data: { ...crumbs, numberOfItems: 2 } })).not.toEqual([]);
    const trip = jsonLd(page(LIVE)).find((b) => b.type === "Trip")!.data;
    expect(jsonLdErrors({ type: "Trip", data: { ...trip, offers: { ...trip.offers, price: "69" } } })).not.toEqual([]);
  });

  it("the home page says who we are: WebSite and Organization", () => {
    expect(jsonLd(page("/")).map((b) => b.type).sort()).toEqual(["Organization", "WebSite"]);
    const org = jsonLd(page("/")).find((b) => b.type === "Organization")!.data;
    expect(org.sameAs).toEqual(["https://www.instagram.com/ondestaanocas/"]);
  });

  it("a live promotion is a Trip with an Offer whose price is the traced price on the page", () => {
    const doc = page(LIVE);
    expect(jsonLd(doc).map((b) => b.type).sort()).toEqual(["BreadcrumbList", "Trip"]);
    const block = jsonLd(doc).find((b) => b.type === "Trip")!;
    const promotion = data.promotions.promotions.find((p) => p.path === LIVE)!;
    // Read off the fixture by hand: obs 7226, 69 €, LIS → FNC, 31 Oct to 3 Nov 2026.
    expect(block.data.offers.price).toBe(69);
    expect(block.el.getAttribute("data-obs")).toBe("7226");
    expect(block.el.getAttribute("data-deal")).toBe(String(promotion.id));
    expect(block.data.offers.url).toBe(BASE + LIVE);
    expect(block.data.tripOrigin).toEqual({ "@type": "Airport", iataCode: "LIS", name: "Lisboa" });
    expect(block.data.itinerary.iataCode).toBe("FNC");
    expect(block.data.subTrip.map((t: any) => [t.name, t.departureTime, t.tripOrigin.iataCode, t.itinerary.iataCode]))
      .toEqual([["Ida", "2026-10-31", "LIS", "FNC"], ["Regresso", "2026-11-03", "FNC", "LIS"]]);
    // The same amount is what the page shows under the same observation.
    const amounts = traceableAmounts(data);
    expect(amounts.obs.get(7226)!.has(6900)).toBe(true);
    expect(text(doc.querySelector(`[data-deal="${promotion.id}"]`)!)).toContain(eur(69));
  });

  it("an expired promotion has no Trip or Offer", () => {
    expect(jsonLd(page(EXPIRED)).map((b) => b.type)).toEqual(["BreadcrumbList"]);
    expect(pageSourceOf(EXPIRED)).not.toContain('"Offer"');
  });

  it("itineraries and tips are Articles by Ponto Nómada, modified when their facts were checked", () => {
    const itinerary = jsonLd(page(ITINERARY)).find((b) => b.type === "Article")!.data;
    expect(itinerary.dateModified).toBe("2026-10-14");
    expect(itinerary.headline).toBe("Paris em 3 dias (roteiro de teste)");
    expect(itinerary.author.name).toBe("Ponto Nómada");
    expect(itinerary.publisher.name).toBe("Ponto Nómada");
    expect(itinerary.mainEntityOfPage).toBe(BASE + ITINERARY);
    const tip = jsonLd(page(TIP)).find((b) => b.type === "Article")!.data;
    expect(tip.dateModified).toBe("2026-10-12");
  });

  it("breadcrumbs follow the visible trail and every crumb is a built page", () => {
    const trail = (path: string) => jsonLd(page(path)).find((b) => b.type === "BreadcrumbList")!
      .data.itemListElement.map((i: any) => [i.position, i.name, i.item.slice(BASE.length)]);
    expect(trail("/destinos/paris/")).toEqual([[1, "Destinos", "/destinos/"], [2, "Paris", "/destinos/paris/"]]);
    expect(trail("/partidas/lisboa/")).toEqual([[1, "Partidas", "/partidas/"], [2, "Lisboa", "/partidas/lisboa/"]]);
    expect(trail("/voos/lisboa-paris/")).toEqual([[1, "Voos desde Lisboa", "/partidas/lisboa/"],
      [2, "Paris", "/destinos/paris/"], [3, "Lisboa → Paris", "/voos/lisboa-paris/"]]);
    expect(trail(ITINERARY)).toEqual([[1, "Roteiros", "/roteiros/"], [2, "Paris em 3 dias (roteiro de teste)", ITINERARY]]);
    expect(trail(TIP)).toEqual([[1, "Dicas", "/dicas/"], [2, "Dica de teste para as páginas do site", TIP]]);
    expect(trail(LIVE)).toEqual([[1, "Promoções", "/"], [2, "Lisboa → Madeira", LIVE]]);
    const pages = new Set(builtPages());
    for (const path of htmlPages()) {
      for (const b of jsonLd(page(path)).filter((x) => x.type === "BreadcrumbList")) {
        for (const i of b.data.itemListElement) expect(pages.has(i.item.slice(BASE.length)), `${path} -> ${i.item}`).toBe(true);
        // The visible trail shows the same names.
        const nav = page(path).querySelector('nav[aria-label="Caminho"]');
        expect(nav, path).not.toBeNull();
        for (const i of b.data.itemListElement.slice(0, -1)) expect(text(nav!), path).toContain(i.name);
      }
    }
  });

  it("keeps the markup safe: no closing tag inside a JSON-LD block", () => {
    for (const path of htmlPages()) {
      for (const b of jsonLd(page(path))) expect(b.el.innerHTML.includes("</"), path).toBe(false);
    }
  });
});

function pageSourceOf(path: string): string {
  return readFileSync(join(distDir(), ...path.split("/").filter(Boolean), "index.html"), "utf8");
}

describe("About and Privacy pages", () => {
  it("are linked from every page's footer", () => {
    for (const path of builtPages()) {
      const footer = page(path).querySelectorAll("footer").at(-1)!;   // the page footer, not an article's
      expect(footer.querySelector('a[href="/sobre/"]'), path).not.toBeNull();
      expect(footer.querySelector('a[href="/privacidade/"]'), path).not.toBeNull();
    }
  });

  it("the privacy page describes the cookieless analytics and the partner's cookies", () => {
    const body = text(page("/privacidade/").querySelector("main")!);
    expect(body).toContain("Cloudflare Web Analytics");
    expect(body).toMatch(/[Nn]ão usa cookies/);
    expect(body).toMatch(/não (define|guarda) cookies/);
    expect(body).toContain("Travelpayouts");
    expect(body).toContain("Aviasales");
    expect(body).toMatch(/só depois de (clicares|carregares)/);
    // The search form loads on the button only (src/lib/search-widget.ts), as this page says.
    expect(body).toContain(`só é carregada quando carregas no botão "${SEARCH_BUTTON}"`);
    expect(body).not.toMatch(/quando chegas a essa parte/);
    expect(page("/privacidade/").querySelector('main a[href="https://www.instagram.com/ondestaanocas/"]')).not.toBeNull();
  });

  it("the About page explains how prices are found, checked and paid for", () => {
    const body = text(page("/sobre/").querySelector("main")!);
    expect(body).toContain("Nunca inventamos nem estimamos preços");
    expect(body).toContain("preço mínimo habitual");
    expect(body).toContain("comissão");
    expect(page("/sobre/").querySelector('main a[href="https://www.instagram.com/ondestaanocas/"]')).not.toBeNull();
  });
});

describe("no third parties and no cookies in a fixture build", () => {
  it("has no analytics beacon and no search widget", () => {
    for (const file of files(distDir()).filter((f) => /\.(html|js|xml|txt|json)$/.test(f))) {
      const source = readFileSync(file, "utf8");
      expect(source.includes("cloudflareinsights"), file).toBe(false);
      expect(/data-search-widget|tp\.media|tpwgts\.com|tpembd\.com|tpemd\.com|tpscr\.com/.test(source), file).toBe(false);
    }
  });

  it("never writes a cookie: no document.cookie in the built site or its sources", () => {
    const sources = [...files(distDir()), ...files(join(WEB, "src")), ...files(join(WEB, "functions"))]
      .filter((f) => /\.(html|js|mjs|ts|astro)$/.test(f));
    for (const file of sources) {
      const source = readFileSync(file, "utf8");
      expect(/document\.cookie|cookieStore|set-cookie/i.test(source), file).toBe(false);
    }
  });
});

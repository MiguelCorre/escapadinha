// Itinerary and tip pages (#17, D33) in the fixture build. The content is the test-only MDX under
// test/fixtures/content/ (a reviewed Paris itinerary checked on 2026-10-14, a draft for Barcelona,
// a reviewed tip checked on 2026-10-12 with two sources) plus the real src/content/ files, built
// once Miguel has reviewed them. Which real entries are reviewed is read from the files, so his
// approving one never breaks these tests.
import { readdirSync, readFileSync } from "node:fs";
import { parseFrontmatter } from "@astrojs/internal-helpers/frontmatter";
import { describe, expect, it } from "vitest";
import { contentPath, isVisible, itinerarySchema, tipSchema, type ContentKind } from "../src/lib/content";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { builtPages, page, pageSource, text } from "./html";

const ITINERARY = "/roteiros/paris-em-3-dias/";
const TIP = "/dicas/dica-de-teste/";
const HUBS = loadSiteData(FIXTURES_DIR).destinations.destinations;

/** Every entry of a collection, real (src/content/) and test-only (test/fixtures/content/), with
 * its front matter as the site reads it and whether the fixture build shows it. */
function entries<T extends { reviewed: boolean; fixture: boolean }>(kind: ContentKind,
  schema: { parse: (front: unknown) => T }) {
  return ["../src/content", "./fixtures/content"].flatMap((folder) => {
    const dir = new URL(`${folder}/${kind}/`, import.meta.url);
    return readdirSync(dir).filter((f) => f.endsWith(".mdx")).map((f) => {
      const data = schema.parse(parseFrontmatter(readFileSync(new URL(f, dir), "utf8")).frontmatter);
      const id = f.replace(/\.mdx$/, "");
      return { id, path: contentPath(kind, id), data, built: isVisible(data, { dev: false, fixtureBuild: true }) };
    });
  });
}
const ITINERARIES = entries("itineraries", itinerarySchema);
const TIPS = entries("tips", tipSchema);

const DRAFTS = [...ITINERARIES, ...TIPS].filter((e) => !e.built).map((e) => e.path);

describe("content pages", () => {
  it("builds reviewed itineraries and tips and lists them", () => {
    expect(builtPages()).toEqual(expect.arrayContaining([ITINERARY, TIP, "/roteiros/", "/dicas/"]));
    expect(page("/roteiros/").querySelector(`main a[href="${ITINERARY}"]`)).not.toBeNull();
    expect(page("/dicas/").querySelector(`main a[href="${TIP}"]`)).not.toBeNull();
    for (const path of [ITINERARY, TIP, "/roteiros/", "/dicas/"]) {
      expect(page(path).querySelector('meta[name="robots"]'), path).toBeNull();
    }
  });

  it("leaves drafts out of the build, the listings and every link", () => {
    expect(DRAFTS).toContain("/roteiros/rascunho-de-teste/");
    const built = builtPages();
    for (const path of DRAFTS) expect(built, path).not.toContain(path);
    for (const path of built.filter((p) => !p.endsWith(".html"))) {
      const source = pageSource(path);
      for (const draft of DRAFTS) expect(source, `${path} links ${draft}`).not.toContain(draft);
      // A draft's title never reaches a page.
      expect(source, path).not.toContain("Rascunho de teste");
    }
  });

  it("says when the facts were checked and links the official sources", () => {
    const tip = page(TIP);
    expect(text(tip.querySelector("main")!)).toContain("Factos verificados a 12 de outubro de 2026");
    const sources = tip.querySelectorAll("[data-sources] a").map((a) => a.getAttribute("href"));
    expect(sources).toEqual(["https://example.com/fonte-oficial", "https://example.org/regras"]);
    expect(text(page(ITINERARY).querySelector("main")!)).toContain("Factos verificados a 14 de outubro de 2026");
  });

  it("renders the MDX body", () => {
    const main = page(TIP).querySelector("main")!;
    expect(main.querySelector("h1")!.textContent).toBe("Dica de teste para as páginas do site");
    expect(main.querySelectorAll("h2").map((h) => h.textContent)).toEqual(
      expect.arrayContaining(["Primeiro passo", "Segundo passo"]));
    expect(main.querySelector("strong")!.textContent).toBe("texto em destaque");
  });

  it("gives an itinerary its days and best months and links the destination hub", () => {
    const main = page(ITINERARY).querySelector("main")!;
    expect(text(main)).toContain("3 dias");
    expect(text(main)).toContain("abril, maio e setembro");
    expect(main.querySelector('a[href="/destinos/paris/"]')).not.toBeNull();
  });
});

describe("itinerary links (D30's hook)", () => {
  it("links the itinerary from the destination hub and the city's route pages", () => {
    for (const path of ["/destinos/paris/", "/voos/lisboa-paris/"]) {
      const link = page(path).querySelector("[data-itinerary] a");
      expect(link?.getAttribute("href"), path).toBe(ITINERARY);
    }
  });

  it("links each hub's reviewed itinerary, the test-only one first, or nothing", () => {
    for (const hub of HUBS) {
      const mine = ITINERARIES.filter((e) => e.built && e.data.destination === hub.code);
      const expected = (mine.find((e) => e.data.fixture) ?? mine[0])?.path ?? null;
      const link = page(hub.path).querySelector("[data-itinerary] a")?.getAttribute("href") ?? null;
      expect(link, hub.path).toBe(expected);
    }
  });
});

describe("related tips on destination hubs (story 36)", () => {
  it("lists the reviewed tips whose destinations name the city", () => {
    const section = page("/destinos/paris/").querySelector("[data-related-tips]")!;
    expect(text(section.querySelector("h2")!)).toBe("Dicas para Paris");
    expect(section.querySelectorAll("a").map((a) => a.getAttribute("href"))).toContain(TIP);
  });

  it("lists exactly those on every hub, and renders nothing where no tip is about the city", () => {
    for (const hub of HUBS) {
      const expected = TIPS.filter((e) => e.built && e.data.destinations.includes(hub.code)).map((e) => e.path);
      const section = page(hub.path).querySelector("[data-related-tips]");
      const links = section?.querySelectorAll("a").map((a) => a.getAttribute("href")) ?? [];
      expect([...links].sort(), hub.path).toEqual([...expected].sort());
      if (!expected.length) expect(section, hub.path).toBeNull();
    }
  });
});

describe("home page", () => {
  it("links the latest itineraries and tips: the first three of each listing", () => {
    const links = (path: string, section: string) => page(path).querySelectorAll(`main li a[href^="${section}"]`)
      .map((a) => a.getAttribute("href"));
    for (const section of ["/roteiros/", "/dicas/"]) {
      const latest = links(section, section).slice(0, 3);
      expect(latest.length, section).toBeGreaterThan(0);
      expect(links("/", section), section).toEqual(latest);
    }
  });
});

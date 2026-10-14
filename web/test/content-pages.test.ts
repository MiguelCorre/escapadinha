// Itinerary and tip pages (#17, D33) in the fixture build. The content is the test-only MDX under
// test/fixtures/content/ (a reviewed Paris itinerary checked on 2026-10-14, a draft for Barcelona,
// a reviewed tip checked on 2026-10-12 with two sources) plus the real src/content/ files: the
// converted "guia rápido" and #19's drafts, all still waiting for Miguel's review.
import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { contentPath, type ContentKind } from "../src/lib/content";
import { builtPages, page, pageSource, text } from "./html";

const ITINERARY = "/roteiros/paris-em-3-dias/";
const TIP = "/dicas/dica-de-teste/";

/** The pages of the real entries (src/content/) whose front matter is not `reviewed: true`. */
function realDrafts(): string[] {
  return (["itineraries", "tips"] as ContentKind[]).flatMap((kind) => {
    const dir = new URL(`../src/content/${kind}/`, import.meta.url);
    return readdirSync(dir).filter((f) => f.endsWith(".mdx"))
      .filter((f) => !/^reviewed:\s*true\s*$/m.test(readFileSync(new URL(f, dir), "utf8").split(/^---\s*$/m)[1] ?? ""))
      .map((f) => contentPath(kind, f.replace(/\.mdx$/, "")));
  });
}

const DRAFTS = ["/roteiros/rascunho-de-teste/", ...realDrafts()];

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
    const built = builtPages();
    for (const path of DRAFTS) expect(built, path).not.toContain(path);
    for (const path of built.filter((p) => !p.endsWith(".html"))) {
      const source = pageSource(path);
      for (const draft of DRAFTS) expect(source, `${path} links ${draft}`).not.toContain(draft);
      // Neither a draft's title nor its body (the converted guide's) reaches a page.
      expect(source, path).not.toContain("Rascunho de teste");
      expect(source, path).not.toContain("Compara Lisboa, Porto e Faro");
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

  it("links nothing where the only itinerary is a draft, or there is none", () => {
    for (const path of ["/destinos/barcelona/", "/destinos/madeira/"]) {
      expect(page(path).querySelector("[data-itinerary]"), path).toBeNull();
    }
  });
});

describe("related tips on destination hubs (story 36)", () => {
  it("lists the reviewed tips whose destinations name the city", () => {
    const section = page("/destinos/paris/").querySelector("[data-related-tips]")!;
    expect(text(section.querySelector("h2")!)).toBe("Dicas para Paris");
    expect(section.querySelectorAll("a").map((a) => a.getAttribute("href"))).toEqual([TIP]);
  });

  it("renders nothing where no tip is about the city", () => {
    for (const path of ["/destinos/barcelona/", "/destinos/madeira/"]) {
      expect(page(path).querySelector("[data-related-tips]"), path).toBeNull();
    }
  });
});

describe("home page", () => {
  it("links the latest itineraries and tips", () => {
    const home = page("/");
    expect(home.querySelector(`main a[href="${ITINERARY}"]`)).not.toBeNull();
    expect(home.querySelector(`main a[href="${TIP}"]`)).not.toBeNull();
  });
});

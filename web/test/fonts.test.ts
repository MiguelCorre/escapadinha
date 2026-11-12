// The brand fonts (D28, D66): every page preloads the roman file of each family, never an italic,
// and every web font stays font-display: optional, so a preloaded font shows on a first visit and a
// late one never moves the layout.
import { describe, expect, it } from "vitest";
import { builtPages, page, pageSource } from "./html";

interface Face { family: string; url: string | null; style: string; display: string }

function faces(source: string): Face[] {
  return [...source.matchAll(/@font-face\{([^}]*)\}/g)].map(([, body]) => ({
    family: /font-family:([^;]+);/.exec(body)![1].replace(/"/g, ""),
    url: /src:url\("([^"]+)"\)/.exec(body)?.[1] ?? null,
    style: /font-style:([^;]+);/.exec(body)![1],
    display: /font-display:([^;]+);/.exec(body)![1],
  }));
}

describe("brand fonts", () => {
  it("preload the two roman files on every page and no italic", () => {
    for (const path of builtPages()) {
      const web = faces(pageSource(path)).filter((f) => f.url);
      const roman = web.filter((f) => f.style === "normal").map((f) => f.url);
      const preloads = page(path).querySelectorAll('link[rel="preload"][as="font"]')
        .map((l) => l.getAttribute("href"));
      expect(roman, path).toHaveLength(2);   // Fraunces and Source Serif 4
      expect(preloads.sort(), path).toEqual(roman.sort());
      for (const link of page(path).querySelectorAll('link[rel="preload"][as="font"]')) {
        expect(link.getAttribute("type"), path).toBe("font/woff2");
        expect(link.hasAttribute("crossorigin"), path).toBe(true);
      }
    }
  });

  it("keep font-display: optional on every web font, so a late file never swaps in", () => {
    const web = faces(pageSource("/")).filter((f) => f.url);
    expect(web).toHaveLength(4);
    for (const face of web) expect(face.display, face.family).toBe("optional");
  });
});

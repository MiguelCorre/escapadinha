// The site built from the fixtures with the two third-party settings filled in (D34): a fake
// Cloudflare Web Analytics token and a fake search widget src, clearly marked as test values.
// The beacon is on every page with the token; the widget box is on route and destination pages
// only, lazily (the script's src only in data-src: no <script src> to the partner in the HTML).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, inject, it } from "vitest";
import { parse } from "node-html-parser";
import { FAKE_ANALYTICS_TOKEN as FAKE_TOKEN, FAKE_SEARCH_WIDGET as FAKE_WIDGET } from "./build-site";
import { builtPagesIn, pageSource } from "./html";

// Built by the global setup (test/build-site.ts), after the plain fixture build.
const distDir = inject("configuredDistDir");

const doc = (path: string) => parse(pageSource(path, distDir), { comment: false });
const pages = () => builtPagesIn(distDir);
const WIDGET_PAGES = /^\/(voos|destinos)\/[^/]+\/$/;

describe("with an analytics token", () => {
  it("every page loads the official Cloudflare Web Analytics beacon with it, deferred", () => {
    for (const path of pages()) {
      const scripts = doc(path).querySelectorAll('script[src="https://static.cloudflareinsights.com/beacon.min.js"]');
      expect(scripts, path).toHaveLength(1);
      expect(scripts[0].hasAttribute("defer"), path).toBe(true);
      expect(JSON.parse(scripts[0].getAttribute("data-cf-beacon")!), path).toEqual({ token: FAKE_TOKEN });
    }
  });
});

describe("with a search widget", () => {
  it("is on route and destination pages, lazy: its src only in data-src", () => {
    const withWidget = pages().filter((p) => WIDGET_PAGES.test(p));
    expect(withWidget.length).toBeGreaterThan(10);
    for (const path of withWidget) {
      const page = doc(path);
      const boxes = page.querySelectorAll("[data-search-widget]");
      expect(boxes, path).toHaveLength(1);
      expect(boxes[0].getAttribute("data-src"), path).toBe(FAKE_WIDGET);
      expect(boxes[0].childNodes.filter((n) => n.toString().trim()).length, path).toBe(0);   // empty until loaded
      expect(page.querySelectorAll('script[src*="tp.media"]'), path).toHaveLength(0);
      // The loader ships with it, and the affiliate disclosure sits next to it.
      const code = page.querySelectorAll("script").map((s) => s.getAttribute("src")?.startsWith("/")
        ? readFileSync(join(distDir, s.getAttribute("src")!), "utf8") : s.textContent);
      expect(code.some((c) => c.includes("data-search-widget") && c.includes("IntersectionObserver")), path).toBe(true);
      const section = page.querySelector("[data-search-widget-section]")!;
      expect(section.textContent, path).toContain("Publicidade:");
    }
  });

  it("is nowhere else: not on the home page, promotions or any other page", () => {
    const others = pages().filter((p) => !WIDGET_PAGES.test(p));
    expect(others).toEqual(expect.arrayContaining(["/", "/promos/8-lisboa-madeira/", "/promos/3-lisboa-paris/", "/explorar/"]));
    for (const path of others) {
      const source = pageSource(path, distDir);
      expect(source.includes("tp.media"), path).toBe(false);
      expect(source.includes("data-search-widget"), path).toBe(false);
    }
  });
});

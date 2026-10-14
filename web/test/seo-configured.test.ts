// The site built from the fixtures with the two third-party settings filled in (D34): a fake
// Cloudflare Web Analytics token and a fake search widget src, clearly marked as test values.
// The beacon is on every page with the token; the widget box is on route and destination pages
// only, behind a button (the script's src only in data-src: nothing from the partner loads
// before the visitor presses it).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, inject, it } from "vitest";
import { parse } from "node-html-parser";
import { FAKE_ANALYTICS_TOKEN as FAKE_TOKEN, FAKE_SEARCH_WIDGET as FAKE_WIDGET } from "./build-site";
import { SEARCH_BUTTON } from "../src/lib/search-widget";
import { builtPagesIn, pageSource, text } from "./html";

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
  it("is on route and destination pages behind a button: nothing from the partner before a click", () => {
    const withWidget = pages().filter((p) => WIDGET_PAGES.test(p));
    expect(withWidget.length).toBeGreaterThan(10);
    for (const path of withWidget) {
      const page = doc(path);
      const boxes = page.querySelectorAll("[data-search-widget]");
      expect(boxes, path).toHaveLength(1);
      expect(boxes[0].getAttribute("data-src"), path).toBe(FAKE_WIDGET);
      // The visitor's explicit action: a real button with the partner's name.
      const button = boxes[0].querySelector("button[data-search-widget-load]")!;
      expect(button.getAttribute("type"), path).toBe("button");
      expect(button.classList.contains("btn"), path).toBe(true);
      expect(text(button), path).toBe(SEARCH_BUTTON);
      const slot = boxes[0].querySelector("[data-search-widget-slot]")!;
      expect(slot.childNodes.filter((n) => n.toString().trim()).length, path).toBe(0);   // empty until pressed
      // The partner's URL appears once, as data: no script, iframe, link or preconnect loads it.
      const source = pageSource(path, distDir);
      expect(source.split(FAKE_WIDGET.replaceAll("&", "&amp;")).length - 1
        + source.split(FAKE_WIDGET).length - 1, path).toBe(1);
      // (Booking links are <a href>: a click, like the button.)
      for (const el of page.querySelectorAll("script, iframe, img, link, source, object, embed")) {
        for (const attr of ["src", "href", "srcset", "data"]) {
          expect(el.getAttribute(attr) ?? "", path).not.toMatch(/tp\.media|tpwgts|tpembd|tpemd|tpscr|aviasales/);
        }
      }
      // The loader ships with it (click only, no IntersectionObserver), and the affiliate
      // disclosure and the cookie note sit next to it.
      const code = page.querySelectorAll("script").map((s) => s.getAttribute("src")?.startsWith("/")
        ? readFileSync(join(distDir, s.getAttribute("src")!), "utf8") : s.textContent);
      const loader = code.filter((c) => c.includes("data-search-widget"));
      expect(loader.length, path).toBeGreaterThan(0);
      expect(loader.some((c) => c.includes("click")), path).toBe(true);
      expect(loader.some((c) => /IntersectionObserver|"scroll"|pointerdown/.test(c)), path).toBe(false);
      const section = page.querySelector("[data-search-widget-section]")!;
      expect(section.textContent, path).toContain("Publicidade:");
      expect(section.textContent, path).toContain("só aparece depois de carregares no botão");
      expect(section.querySelector('a[href="/privacidade/"]'), path).not.toBeNull();
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

// Itineraries and tips (#17, D33): the front matter schemas, the review gate and the itinerary
// lookup behind ItineraryLink, on hand-made entries. The built pages are in content-pages.test.ts.
import { describe, expect, it } from "vitest";
import { contentPath, isVisible, itinerarySchema, tipSchema } from "../src/lib/content";
import { itineraryFor } from "../src/lib/itinerary";

const SOURCE = { title: "Turismo de Paris", url: "https://www.parisjetaime.com/" };
const ITINERARY = {
  title: "Paris em 3 dias",
  description: "Três dias em Paris a pé e de metro.",
  destination: "PAR",
  days: 3,
  best_months: [4, 5, 9],
  last_checked: new Date("2026-10-14"),
  sources: [SOURCE],
  reviewed: true,
};
const TIP = {
  title: "Voos baratos desde Portugal",
  description: "Hábitos que fazem baixar o preço.",
  topic: "voos",
  last_checked: "2026-10-14",
  sources: [SOURCE],
  reviewed: true,
};

describe("front matter", () => {
  it("reads an itinerary, the last-checked date as an ISO day", () => {
    const it = itinerarySchema.parse(ITINERARY);
    expect(it.last_checked).toBe("2026-10-14");
    expect(it.fixture).toBe(false);
    expect(tipSchema.parse(TIP).last_checked).toBe("2026-10-14");
  });

  it("is a draft unless it says reviewed", () => {
    const { reviewed: _r, last_checked: _l, sources: _s, ...draft } = ITINERARY;
    const parsed = itinerarySchema.parse(draft);
    expect(parsed.reviewed).toBe(false);
    expect(parsed.sources).toEqual([]);
  });

  it("refuses a reviewed entry without a last-checked date or an official source", () => {
    expect(itinerarySchema.safeParse({ ...ITINERARY, last_checked: undefined }).success).toBe(false);
    expect(tipSchema.safeParse({ ...TIP, sources: [] }).success).toBe(false);
  });

  it("refuses sources that are not https links, unknown city codes and bad months", () => {
    expect(tipSchema.safeParse({ ...TIP, sources: [{ title: "x", url: "http://example.com/" }] }).success).toBe(false);
    expect(itinerarySchema.safeParse({ ...ITINERARY, destination: "Paris" }).success).toBe(false);
    expect(itinerarySchema.safeParse({ ...ITINERARY, best_months: [13] }).success).toBe(false);
    expect(itinerarySchema.safeParse({ ...ITINERARY, days: 0 }).success).toBe(false);
  });

  it("takes an old site path to redirect from, nothing else", () => {
    expect(tipSchema.parse({ ...TIP, legacy_path: "/guias/voos-baratos-dicas/" }).legacy_path)
      .toBe("/guias/voos-baratos-dicas/");
    expect(tipSchema.safeParse({ ...TIP, legacy_path: "https://example.com/" }).success).toBe(false);
  });
});

describe("review gate", () => {
  const reviewed = { reviewed: true, fixture: false };
  const draft = { reviewed: false, fixture: false };
  const fixture = { reviewed: true, fixture: true };

  it("builds reviewed entries only; drafts show in the local dev server", () => {
    expect(isVisible(reviewed, { dev: false, fixtureBuild: false })).toBe(true);
    expect(isVisible(draft, { dev: false, fixtureBuild: false })).toBe(false);
    expect(isVisible(draft, { dev: false, fixtureBuild: true })).toBe(false);
    expect(isVisible(draft, { dev: true, fixtureBuild: false })).toBe(true);
  });

  it("never builds test-only entries from real data", () => {
    expect(isVisible(fixture, { dev: false, fixtureBuild: true })).toBe(true);
    expect(isVisible(fixture, { dev: false, fixtureBuild: false })).toBe(false);
    expect(isVisible(fixture, { dev: true, fixtureBuild: false })).toBe(false);
  });
});

describe("paths", () => {
  it("puts itineraries under /roteiros/ and tips under /dicas/", () => {
    expect(contentPath("itineraries", "paris-em-3-dias")).toBe("/roteiros/paris-em-3-dias/");
    expect(contentPath("tips", "voos-baratos")).toBe("/dicas/voos-baratos/");
  });

  it("refuses a file name that is not a slug", () => {
    expect(() => contentPath("tips", "Voos Baratos")).toThrow(/slug/);
  });
});

describe("itinerary for a destination", () => {
  const entry = (id: string, destination: string, reviewed = true) =>
    ({ id, data: { title: `Roteiro ${id}`, destination, reviewed } });

  it("links the destination's itinerary, or nothing", () => {
    const entries = [entry("paris-em-3-dias", "PAR"), entry("roma-em-2-dias", "ROM")];
    expect(itineraryFor("PAR", entries)).toEqual({ path: "/roteiros/paris-em-3-dias/", title: "Roteiro paris-em-3-dias" });
    expect(itineraryFor("BCN", entries)).toBeNull();
  });

  it("prefers the reviewed one over a draft (dev server), and refuses two reviewed ones", () => {
    expect(itineraryFor("PAR", [entry("rascunho", "PAR", false), entry("paris", "PAR")])!.path).toBe("/roteiros/paris/");
    expect(() => itineraryFor("PAR", [entry("a", "PAR"), entry("b", "PAR")])).toThrow(/PAR/);
  });
});

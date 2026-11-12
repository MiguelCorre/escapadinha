// Expired promotions on a route page and in /promos/ (D60, D66): the most recent
// EXPIRED_CARDS_PER_ROUTE of a route as cards, the older ones one line each inside a native
// <details>, each line a link to its own page with its price on its data-obs. In the fixtures
// LIS-FNC has 19 expired page promotions (the walk-through's /voos/lisboa-madeira/), LIS-PAR 3.
import { describe, expect, it } from "vitest";
import { EXPIRED_CARDS_PER_ROUTE, expiredOnRoute } from "../src/lib/promotion";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { page, text } from "./html";
import type { HTMLElement } from "node-html-parser";

const data = loadSiteData(FIXTURES_DIR);
const route = (key: string) => data.routes.routes.find((r) => r.key === key)!;

function checkRecord(section: HTMLElement, key: string) {
  const expired = expiredOnRoute(data, key);
  const cards = section.querySelectorAll("article[data-deal]").map((c) => Number(c.getAttribute("data-deal")));
  expect(cards).toEqual(expired.slice(0, EXPIRED_CARDS_PER_ROUTE).map((p) => p.id));
  const lines = section.querySelectorAll("details[data-expired-record] li[data-deal]");
  const older = expired.slice(EXPIRED_CARDS_PER_ROUTE);
  expect(lines.map((l) => Number(l.getAttribute("data-deal")))).toEqual(older.map((p) => p.id));
  for (const [i, line] of lines.entries()) {
    const p = older[i];
    expect(line.querySelector("a")!.getAttribute("href")).toBe(p.path);   // no URL left without a link
    expect(Number(line.querySelector("[data-obs]")!.getAttribute("data-obs"))).toBe(p.offer.obs);
  }
  if (older.length) {
    const details = section.querySelector("details[data-expired-record]")!;
    expect(details.hasAttribute("open")).toBe(false);
    expect(text(details.querySelector("summary")!)).toBe(`${older.length} promoções anteriores`);
  } else {
    expect(section.querySelector("details[data-expired-record]")).toBeNull();
  }
}

describe("expired promotions of a route", () => {
  it("are three cards and a compact record on the route page", () => {
    const doc = page(route("LIS-FNC").path);
    const section = doc.querySelector('section[aria-labelledby="titulo-expiradas"]')!;
    expect(expiredOnRoute(data, "LIS-FNC").length).toBe(19);
    checkRecord(section, "LIS-FNC");
    expect(section.querySelectorAll("details li").length).toBe(16);
  });

  it("are all cards when there are no more than three", () => {
    const section = page(route("LIS-PAR").path).querySelector('section[aria-labelledby="titulo-expiradas"]')!;
    checkRecord(section, "LIS-PAR");
  });

  it("split the same way in every /promos/ group", () => {
    const doc = page("/promos/");
    for (const g of doc.querySelectorAll("[data-route-group]")) checkRecord(g, g.getAttribute("data-route-group")!);
  });
});

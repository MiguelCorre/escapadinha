// School holidays (D61, #49): the filter rule, the data's review gate, and the pages and the
// explorer's filter in the configured build (test/build-site.ts gives it a reviewed calendar: a
// break with fixture low prices inside its window, one already past, one with none). The
// committed fixture is the real draft (unreviewed), so the fixture build has no break page.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "node-html-parser";
import { describe, expect, inject, it } from "vitest";
import type { LowPriceRow } from "../src/lib/contract";
import { NO_FILTERS, explore, fitsWindow } from "../src/lib/explorer";
import { schoolHolidayName, schoolHolidayTitle } from "../src/lib/format";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { SCHOOL_BREAKS } from "./build-site";
import { builtPages, builtPagesIn, page, pageSource, text } from "./html";

const configuredDist = inject("configuredDistDir");
const configured = (path: string) => parse(pageSource(path, configuredDist), { comment: false });
const [WITH_PRICES, PAST, EMPTY] = SCHOOL_BREAKS;
const LISBOA = (slug: string) => `/ferias-escolares/${slug}/lisboa/`;

function row(obs: number, dep: string, ret: string): LowPriceRow {
  return [obs, "PAR", 60, dep, ret, "2026-11-01", "2026-11-01T10:00Z", "FR", 0, "ORY", 100, null, null, null];
}

describe("the school-break rule", () => {
  it("fits a trip whose departure and return are both inside the window", () => {
    const w = { start: "2026-12-15", end: "2027-01-01" };
    expect(fitsWindow("2026-12-15", "2026-12-20", w)).toBe(true);
    expect(fitsWindow("2026-12-28", "2027-01-01", w)).toBe(true);
    expect(fitsWindow("2026-12-14", "2026-12-20", w)).toBe(false);
    expect(fitsWindow("2026-12-28", "2027-01-02", w)).toBe(false);
    expect(fitsWindow("2026-12-20", "2026-12-20", w)).toBe(false);     // a return before or on departure
  });

  it("filters the explorer's rows by a break's slug, and ignores an unknown slug", () => {
    const rows = [row(1, "2026-12-16", "2026-12-20"), row(2, "2026-12-10", "2026-12-20"), row(3, "2026-12-26", "2027-01-03")];
    const breaks = [{ slug: "natal-2026-continente", window: { start: "2026-12-15", end: "2027-01-01" } }];
    expect(explore(rows, { ...NO_FILTERS, ferias: "natal-2026-continente" }, [], {}, breaks).map((r) => r.row[0])).toEqual([1]);
    expect(explore(rows, { ...NO_FILTERS, ferias: "nenhum" }, [], {}, breaks)).toEqual([]);
    expect(explore(rows, NO_FILTERS, [], {}, breaks)).toHaveLength(1);          // one destination, cheapest
  });

  it("names a break with its year and network, pt-PT", () => {
    expect(schoolHolidayName("Férias de Natal", "2026-12-16", "Madeira")).toBe("Férias de Natal 2026 (Madeira)");
    expect(schoolHolidayTitle("Férias de Natal", "2026-12-16", "Continente", { name: "Porto", article: "o" }))
      .toBe("Férias de Natal 2026 (Continente) desde o Porto");
  });
});

describe("the committed calendar (reviewed 2026-11-05)", () => {
  const data = loadSiteData(FIXTURES_DIR);

  it("carries the three networks and their twelve breaks, so the fixture build has a page per break and origin", () => {
    expect(data.schoolHolidays.reviewed).toBe(true);
    expect(data.schoolHolidays.networks.map((n) => n.key)).toEqual(["continente", "madeira", "acores"]);
    expect(data.schoolHolidays.breaks).toHaveLength(12);
    const expected = data.schoolHolidays.breaks.flatMap((b) => b.origins.map((o) => o.path)).sort();
    expect(builtPages().filter((p) => p.startsWith("/ferias-escolares/")).sort()).toEqual(expected);
    expect(expected).toContain("/ferias-escolares/natal-2026-madeira/lisboa/");
  });

  it("every fixture break page either lists prices inside its window or is noindex and says so", () => {
    for (const b of data.schoolHolidays.breaks) {
      for (const o of b.origins) {
        const doc = page(o.path);
        const rows = doc.querySelectorAll("#explorer-results > li[data-obs]");
        const noindex = doc.querySelector('meta[name="robots"]')?.getAttribute("content") ?? null;
        if (rows.length) {
          expect(noindex, o.path).toBeNull();
          const lis = data.lowPrices[o.iata].rows;
          for (const li of rows) {
            const r = lis.find((x) => x[0] === Number(li.getAttribute("data-obs")))!;
            expect(fitsWindow(r[3], r[4], b.window), `${o.path} ${r[0]}`).toBe(true);
          }
        } else {
          expect(noindex, o.path).toBe("noindex");
          expect(text(doc.querySelector("main")!), o.path).toContain("Ainda não há preços baixos para estas datas");
        }
      }
    }
  });

  it("the explorer offers the twelve breaks and an origin page links its twelve pages", () => {
    const options = page("/explorar/").querySelectorAll("select[name=ferias] option").map((o) => o.getAttribute("value"));
    expect(options).toEqual(["", ...data.schoolHolidays.breaks.map((b) => b.slug)]);
    expect(page("/explorar/").querySelectorAll("#ferias-escolares [data-school-holiday]")).toHaveLength(12);
    expect(page("/partidas/lisboa/").querySelectorAll("[data-school-holidays] a")).toHaveLength(12);
  });
});

describe("break pages and the explorer's filter (configured build, reviewed calendar)", () => {
  it("builds one page per break and origin", () => {
    const pages = builtPagesIn(configuredDist).filter((p) => p.startsWith("/ferias-escolares/")).sort();
    const data = loadSiteData(FIXTURES_DIR);
    const expected = SCHOOL_BREAKS.flatMap((b) => data.origins.origins.map((o) => `/ferias-escolares/${b.slug}/${o.slug}/`)).sort();
    expect(pages).toEqual(expected);
  });

  it("a break with low prices inside its window lists them, traced, and is indexable", () => {
    const doc = configured(LISBOA(WITH_PRICES.slug));
    expect(text(doc.querySelector("h1")!)).toBe("Férias de teste 2026 (Continente) desde Lisboa");
    expect(doc.querySelector('meta[name="robots"]')).toBeNull();
    const items = doc.querySelectorAll("#explorer-results > li[data-obs]");
    expect(items.length).toBeGreaterThan(0);
    const lis = loadSiteData(FIXTURES_DIR).lowPrices.LIS.rows;
    for (const li of items) {
      const r = lis.find((x) => x[0] === Number(li.getAttribute("data-obs")))!;
      expect(fitsWindow(r[3], r[4], WITH_PRICES.window), String(r[0])).toBe(true);
    }
    const body = text(doc.querySelector("main")!);
    expect(body).toContain("Férias de teste 2026 (Continente): 5 a 20 de dezembro, sem aulas.");
    expect(body).toContain("partida a partir de 4 de dezembro e regresso até 21 de dezembro");
    expect(body).toContain("Despacho de teste");
    expect(doc.querySelector('[data-source] a[href="https://example.com/despacho-de-teste"]')).not.toBeNull();
    expect(doc.querySelector('[data-other-origins] a[href="/ferias-escolares/teste-dezembro-2026-continente/porto/"]')).not.toBeNull();
  });

  it("a break that has passed, or one without a price, is noindex and says so", () => {
    const past = configured(LISBOA(PAST.slug));
    expect(past.querySelector('meta[name="robots"]')!.getAttribute("content")).toBe("noindex");
    expect(past.querySelector("[data-past]")).not.toBeNull();
    expect(past.querySelector("#explorer-results")).toBeNull();
    const empty = configured(LISBOA(EMPTY.slug));
    expect(empty.querySelector('meta[name="robots"]')!.getAttribute("content")).toBe("noindex");
    expect(text(empty.querySelector("main")!)).toContain("Ainda não há preços baixos para estas datas");
    expect(text(empty.querySelector("h1")!)).toBe("Férias de teste 2027 (Madeira) desde Lisboa");
  });

  it("the explorer offers the upcoming breaks (not the past one) and lists them with a link per origin", () => {
    const doc = configured("/explorar/");
    const options = doc.querySelectorAll("select[name=ferias] option").map((o) => o.getAttribute("value"));
    expect(options).toEqual(["", WITH_PRICES.slug, EMPTY.slug]);
    const items = doc.querySelectorAll("#ferias-escolares [data-school-holiday]").map((li) => li.getAttribute("data-school-holiday"));
    expect(items).toEqual([WITH_PRICES.slug, EMPTY.slug]);
    expect(doc.querySelector(`#ferias-escolares a[href="${LISBOA(WITH_PRICES.slug)}"]`)!.getAttribute("aria-label"))
      .toBe("Férias de teste 2026 (Continente) desde Lisboa");
    // The island's config carries the same windows, so the filter works after a redraw.
    const config = JSON.parse(doc.querySelector("#explorer-config")!.textContent);
    expect(config.ferias.map((b: { slug: string }) => b.slug)).toEqual([WITH_PRICES.slug, EMPTY.slug]);
  });

  it("an origin page links its pages for the upcoming breaks", () => {
    const links = configured("/partidas/lisboa/").querySelectorAll("[data-school-holidays] a");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([LISBOA(WITH_PRICES.slug), LISBOA(EMPTY.slug)]);
    expect(text(links[0])).toBe("Férias de teste 2026 (Continente)");
  });

  it("the sitemap lists only the break pages with prices", () => {
    const sitemap = readFileSync(join(configuredDist, "sitemap.xml"), "utf8");
    expect(sitemap).toContain(LISBOA(WITH_PRICES.slug));
    expect(sitemap).not.toContain(LISBOA(PAST.slug));
    expect(sitemap).not.toContain(LISBOA(EMPTY.slug));
  });
});

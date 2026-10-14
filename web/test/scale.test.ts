// The site at full size (#14 acceptance: ~300 route pages, 6 origin pages, ~150 destination pages
// build within the build-time budget): a synthetic contract dataset the size of the real data
// (test/synthetic-data.ts, 360 routes, 6 origins, 156 destinations, fixture data) is built once
// into a temporary folder; the build time is measured and printed, and the pages are checked like
// the fixture build: counts, dormant notice, months without enough data, internal links, prices.
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { parse } from "node-html-parser";
import { loadSiteData } from "../src/lib/site-data";
import { brokenLinks, builtPagesIn, pageSource } from "./html";
import { writeSyntheticData, type Synthetic } from "./synthetic-data";
import { traceableAmounts, untraceable } from "./trace";

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
/** Build-time budget for the full-size site (D30): measured ~30-40 s on Miguel's PC. */
export const BUILD_BUDGET_SECONDS = 120;

let dataDir = "";
let distDir = "";
let synthetic: Synthetic;
let seconds = 0;

beforeAll(() => {
  dataDir = mkdtempSync(join(tmpdir(), "pn-scale-data-"));
  distDir = mkdtempSync(join(tmpdir(), "pn-scale-dist-"));
  synthetic = writeSyntheticData(dataDir);
  const started = performance.now();
  const result = spawnSync(
    process.execPath,
    [join(WEB_DIR, "node_modules/astro/bin/astro.mjs"), "build", "--outDir", distDir],
    { cwd: WEB_DIR, encoding: "utf8", env: { ...process.env, SITE_DATA_DIR: dataDir, ASTRO_TELEMETRY_DISABLED: "1" } },
  );
  seconds = (performance.now() - started) / 1000;
  if (result.status !== 0) throw new Error(`astro build failed:\n${result.stdout}\n${result.stderr}`);
  console.info(`scale build: ${builtPagesIn(distDir).length} pages in ${seconds.toFixed(1)} s`);
}, 600_000);

afterAll(() => {
  for (const dir of [dataDir, distDir]) if (dir) rmSync(dir, { recursive: true, force: true });
});

const doc = (path: string) => parse(pageSource(path, distDir), { comment: false });

describe("full-size build (synthetic data)", () => {
  it("is valid contract data of the real data's size", () => {
    const data = loadSiteData(dataDir);
    expect(data.meta.fixture).toBe(true);
    expect(data.routes.routes).toHaveLength(360);
    expect(data.origins.origins).toHaveLength(6);
    expect(data.destinations.destinations.length).toBeGreaterThanOrEqual(150);
    expect(synthetic.dormant.length).toBeGreaterThan(0);
  });

  it("builds every route, origin and destination page within the budget", () => {
    const pages = builtPagesIn(distDir);
    expect(pages.filter((p) => p.startsWith("/voos/"))).toHaveLength(360);
    expect(pages.filter((p) => /^\/partidas\/[^/]+\/$/.test(p))).toHaveLength(6);
    expect(pages.filter((p) => /^\/destinos\/[^/]+\/$/.test(p))).toHaveLength(synthetic.destinations.length);
    expect(seconds).toBeLessThan(BUILD_BUDGET_SECONDS);
  });

  it("shows the dormant notice on dormant routes only", () => {
    const [dormant] = synthetic.dormant;
    const notice = doc(dormant.path).querySelector("[data-dormant]")!;
    expect(notice.textContent).toContain("Rota adormecida");
    expect(notice.textContent).toContain("01/09/2026");           // last price seen
    const active = synthetic.routes.find((r) => r.status === "active")!;
    expect(doc(active.path).querySelector("[data-dormant]")).toBeNull();
    const origin = synthetic.origins.find((o) => o.iata === dormant.origin)!;
    expect(doc(origin.path).querySelector(`li[data-route="${dormant.key}"]`)!.textContent).toContain("adormecida");
  });

  it("says when a month has too few days instead of showing a number", () => {
    const route = synthetic.routes.find((r) => r.status === "active"
      && r.months.some((m) => m.typical_low == null) && r.months.some((m) => m.typical_low != null))!;
    const rows = doc(route.path).querySelectorAll("[data-months] tbody tr");
    route.months.forEach((m, i) => {
      const text = rows[i].textContent;
      if (m.typical_low == null) {
        expect(text).toContain("ainda sem dados suficientes");
        expect(text).not.toMatch(/€/);
      } else expect(text).toMatch(/€/);
    });
  });

  it("only links to pages that exist", () => {
    expect(brokenLinks(distDir)).toEqual([]);
  });

  it("traces every price on the route, origin and destination pages", () => {
    const amounts = traceableAmounts(loadSiteData(dataDir));
    const problems: string[] = [];
    let checked = 0;
    for (const path of builtPagesIn(distDir)) {
      const result = untraceable(pageSource(path, distDir), amounts);
      checked += result.checked;
      problems.push(...result.problems.map((p) => `${path}: ${p}`));
    }
    expect(problems.slice(0, 10)).toEqual([]);
    expect(checked).toBeGreaterThan(10_000);
  });
});

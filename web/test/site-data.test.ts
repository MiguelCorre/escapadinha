// The build's only input: the contract JSON in SITE_DATA_DIR, validated against
// contract/site/v1/*.schema.json before anything is rendered.
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";

const scratch: string[] = [];

function fixtureCopy(): string {
  const dir = mkdtempSync(join(tmpdir(), "pn-site-data-"));
  scratch.push(dir);
  cpSync(FIXTURES_DIR, dir, { recursive: true });
  return dir;
}

function edit(dir: string, file: string, change: (json: any) => void): void {
  const path = join(dir, file);
  const json = JSON.parse(readFileSync(path, "utf8"));
  change(json);
  writeFileSync(path, JSON.stringify(json));
}

afterEach(() => {
  for (const dir of scratch.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe("loadSiteData", () => {
  it("loads the committed fixtures", () => {
    const data = loadSiteData(FIXTURES_DIR);
    expect(data.meta.fixture).toBe(true);
    expect(data.promotions.promotions.map((p) => p.id)).toEqual([3, 2]);
    expect(Object.keys(data.lowPrices).sort()).toEqual(["FAO", "LIS", "OPO"]);
    expect(data.labels.disclosure.site).toMatch(/^Publicidade/);
  });

  it("fails loudly when the directory is missing", () => {
    expect(() => loadSiteData(join(tmpdir(), "pn-no-such-dir"))).toThrow(/SITE_DATA_DIR/);
  });

  it("names the file and the field when the data breaks the schema", () => {
    const dir = fixtureCopy();
    edit(dir, "promotions.json", (j) => { j.promotions[0].offer.price = -5; });
    expect(() => loadSiteData(dir)).toThrow(/promotions\.json.*\/promotions\/0\/offer\/price/s);
  });

  it("fails when a low-price file listed in meta.json is missing", () => {
    const dir = fixtureCopy();
    rmSync(join(dir, "low-prices", "OPO.json"));
    expect(() => loadSiteData(dir)).toThrow(/low-prices\/OPO\.json/);
  });

  it("loads the upcoming long weekends (pontes, D31), validated", () => {
    const data = loadSiteData(FIXTURES_DIR);
    expect(data.pontes.pontes[0].slug).toBe("1-dezembro-2026");
    expect(data.pontes.pontes[0].window).toEqual({ start: "2026-11-27", end: "2026-12-02" });
    const dir = fixtureCopy();
    edit(dir, "pontes.json", (j) => { j.pontes[0].window.start = "27/11/2026"; });
    expect(() => loadSiteData(dir)).toThrow(/pontes\.json.*\/pontes\/0\/window\/start/s);
  });

  it("reads an export from before pontes.json as one without long weekends", () => {
    const dir = fixtureCopy();
    edit(dir, "meta.json", (j) => { delete j.files.pontes; });
    rmSync(join(dir, "pontes.json"));
    expect(loadSiteData(dir).pontes.pontes).toEqual([]);
  });

  it("refuses another contract version", () => {
    const dir = fixtureCopy();
    edit(dir, "meta.json", (j) => { j.version = 2; });
    expect(() => loadSiteData(dir)).toThrow(/meta\.json/);
  });
});

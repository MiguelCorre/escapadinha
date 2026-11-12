// Airline and airport names (D66): a page never shows "Chegada: PRG", "Aeroporto de chegada: FNC"
// or "com a QS" where a name belongs. An airport the labels do not name is named by its city when
// it is its route's (or destination's) only airport; any other unknown code stays the code.
import { describe, expect, it } from "vitest";
import { arrivalAirport } from "../src/lib/promotion";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { builtPages, page, text } from "./html";

const BARE_ARRIVAL = /(?:Chegada|chegada|Chegada a):?\s+([A-Z0-9]{3})(?![\w(])(?!\s*\()/;
const BARE_AIRLINE = /\bcom a ([A-Z0-9]{2})\b/;

describe("airline and airport names", () => {
  it("never show a bare code on a built page", () => {
    for (const path of builtPages()) {
      const body = text(page(path).querySelector("body")!);
      expect(body.match(BARE_ARRIVAL)?.[0] ?? null, path).toBeNull();
      expect(body.match(BARE_AIRLINE)?.[0] ?? null, path).toBeNull();
    }
  });

  it("name an airport by the labels, else by its city when it is the only one", () => {
    const data = loadSiteData(FIXTURES_DIR);
    expect(arrivalAirport(data, "BVA", ["BVA", "CDG", "ORY"], "Paris")).toEqual({ name: "Beauvais", remote: true });
    expect(arrivalAirport(data, "XQZ", ["XQZ"], "Cidade")).toEqual({ name: "Cidade", remote: false });
    expect(arrivalAirport(data, "XQZ", ["XQZ", "XQY"], "Cidade")).toBeUndefined();   // not the only one
    expect(arrivalAirport(data, "XQZ", ["XQY"], "Cidade")).toBeUndefined();          // landed elsewhere
  });

  it("never label a destination with a region it may not be in (D66)", () => {
    const data = loadSiteData(FIXTURES_DIR);
    expect(data.labels.kinds.europe).toBe("Curto e médio curso");
    for (const path of builtPages()) {
      for (const el of page(path).querySelectorAll(".label, .text-small")) {
        expect(text(el), path).not.toMatch(/^Europa/);
      }
    }
  });
});

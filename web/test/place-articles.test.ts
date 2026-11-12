// Destinations that take an article read right in pt-PT (D66): the fixture's Madeira (a), Porto (o)
// and Rio de Janeiro (o) on their hub, route and itinerary lines; a destination never lists itself
// among the origins we do not follow yet.
import { describe, expect, it } from "vitest";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { page, text } from "./html";

const data = loadSiteData(FIXTURES_DIR);
const hub = (code: string) => data.destinations.destinations.find((d) => d.code === code)!;
const route = (key: string) => data.routes.routes.find((r) => r.key === key)!;

describe("place names with their article", () => {
  it("carry the article from destinations.json", () => {
    expect(hub("FNC").article).toBe("a");
    expect(hub("RIO").article).toBe("o");
    expect(hub("PAR").article ?? null).toBeNull();
  });

  it("read 'para a Madeira' on the hub and never list Madeira as its own origin", () => {
    const doc = page(hub("FNC").path);
    expect(text(doc.querySelector("title")!)).toBe("Voos baratos para a Madeira desde Portugal · Ponto Nómada");
    const body = text(doc.querySelector("main")!);
    expect(body).not.toMatch(/para Madeira|desde Madeira|em Madeira/);
    expect(body).toMatch(/voos para a Madeira desde/);
  });

  it("read 'do Porto para a Madeira' on a route page, origin and destination contracted", () => {
    const doc = page(route("OPO-FNC").path);
    expect(text(doc.querySelector("h1")!)).toBe("Voos do Porto para a Madeira");
    expect(text(doc.querySelector("title")!)).toBe("Voos baratos do Porto para a Madeira · Ponto Nómada");
    expect(text(page(route("LIS-PAR").path).querySelector("h1")!)).toBe("Voos de Lisboa para Paris");
  });

  it("read 'desde o Porto' on an origin page and the destinations index", () => {
    const porto = data.origins.origins.find((o) => o.iata === "OPO")!;
    expect(text(page(porto.path).querySelector("h1")!)).toBe("Voos desde o Porto");
    expect(text(page("/destinos/").querySelector("main")!)).toContain("Desde o Porto");
  });

  it("never writes a destination that takes an article without it", () => {
    const named = data.destinations.destinations.filter((d) => d.article);
    for (const d of named) {
      for (const path of [d.path, ...d.routes.map((k) => route(k)?.path).filter(Boolean)]) {
        const body = text(page(path!).querySelector("html")!);
        expect(body, path!).not.toMatch(new RegExp(`\b(para|em|de|desde) ${d.city}\b`));
      }
    }
  });
});

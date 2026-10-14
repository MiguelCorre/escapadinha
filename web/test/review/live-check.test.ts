// The Function's live check is a port of the pipeline's (D26, D29): the shared cases in
// contract/review/v1/fixtures/live-check-cases.json run here and in tests/test_live_check_cases.py.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CheckError, liveCheck, recheckPayload } from "../../functions/_lib/review/live-check";
import { CONTRACT, deal, FakeNet, item, NOW, PRICES, pricesPayload } from "./helpers";

const CASES = JSON.parse(readFileSync(resolve(CONTRACT, "fixtures/live-check-cases.json"), "utf8"));

function target(c: any) {
  const d = { ...CASES.defaults.deal, ...(c.deal ?? {}) };
  return {
    price_eur: d.price_eur, departure_date: d.departure_date, return_date: d.return_date, direct: d.direct,
    live_check: { query: {}, rules: d.rules },
  };
}

function payload(c: any) {
  return c.payload ?? { success: true, currency: "eur",
    data: c.items.map((i: any) => ({ ...CASES.defaults.item, ...i })) };
}

describe("live check: shared cases with the pipeline", () => {
  it.each(CASES.cases.map((c: any) => [c.name, c]))("%s", (_, c: any) => {
    const now = new Date(c.now ?? CASES.defaults.now);
    if (c.expected.error) {
      expect(() => recheckPayload(target(c), payload(c), now)).toThrow(new CheckError(c.expected.error));
      return;
    }
    expect(recheckPayload(target(c), payload(c), now)).toEqual(c.expected);
  });
});

describe("live check request", () => {
  it("asks the provider exactly the snapshot's query, token in the header", async () => {
    const net = new FakeNet().on(PRICES, () => Response.json(pricesPayload(item(58))));
    const d = deal(7) as any;
    const result = await liveCheck(d, { token: "tp-secret", fetch: net.fetch, now: () => NOW });
    expect(result).toEqual({ valid: true, price_eur: 58, reason: "continua a 58 €", checked_at: "2026-10-14T09:30:00Z" });
    const [call] = net.calls;
    const url = new URL(call.url);
    expect(`${url.origin}${url.pathname}`).toBe(PRICES);
    expect(Object.fromEntries(url.searchParams)).toEqual({ origin: "LIS", destination: "LON", departure_at: "2026-11",
      one_way: "false", currency: "eur", sorting: "price", unique: "false", limit: "1000", market: "pt" });
    expect(call.headers.get("X-Access-Token")).toBe("tp-secret");
    expect(call.url).not.toContain("tp-secret");
  });

  it.each([
    ["an HTTP error", () => new Response("Too Many Requests", { status: 429 }), "HTTP 429: Too Many Requests"],
    ["a provider error", () => Response.json({ success: false, error: "bad token" }), "API error: bad token"],
    ["no answer", () => { throw new TypeError("network down"); }, "network down"],
  ])("turns %s into a pt-PT reason", async (_, route, detail) => {
    const net = new FakeNet().on(PRICES, route as any);
    await expect(liveCheck(deal(7) as any, { token: "t", fetch: net.fetch, now: () => NOW }))
      .rejects.toThrow(`Não foi possível verificar o preço agora: ${detail}`);
  });
});

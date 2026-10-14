// Decisions from the phone (#9, D29): the Function writes one review event per decision
// (contract/review/v1/event.schema.json) under review/events/pending/, then fires exactly one
// repository_dispatch. It never changes a status: the pipeline's applier does (D26).
import { describe, expect, it } from "vitest";
import { handle } from "../../functions/_lib/review/handler";
import { DISPATCH, deal, EMAIL, item, post, PRICES, pricesPayload, schemaErrors, snapshot, world } from "./helpers";

const PENDING = "review/events/pending/";

async function decide(w: Awaited<ReturnType<typeof world>>, body: unknown, headers: Record<string, string> = {}) {
  const res = await handle(post("/review/decision", body, w.token, headers), w.env, w.deps);
  return { res, body: (await res.json()) as any };
}

describe("approve", () => {
  it("checks the price live, writes one approve event with the check and dispatches once", async () => {
    const w = await world();
    const { res, body } = await decide(w, { type: "approve", deal_id: 7, note: "bom preço" });
    expect(res.status).toBe(200);
    const [key] = w.store.keys(PENDING);
    expect(w.store.keys(PENDING)).toHaveLength(1);
    expect(key).toMatch(/^review\/events\/pending\/20261014T093000Z-[0-9a-f-]{36}\.json$/);
    const event = w.store.json(key);
    expect(schemaErrors("event", event)).toEqual([]);
    expect(key).toBe(`${PENDING}20261014T093000Z-${event.id}.json`);
    expect(event).toMatchObject({
      version: 1, type: "approve", deal_id: 7, created_at: "2026-10-14T09:30:00Z", actor: EMAIL,
      note: "bom preço", post_url: null,
      live_check: { valid: true, price_eur: 58, reason: "continua a 58 €", checked_at: "2026-10-14T09:30:00Z" },
    });
    expect(w.net.to(PRICES)).toHaveLength(1);
    const dispatches = w.net.to(DISPATCH);
    expect(dispatches).toHaveLength(1);
    expect(dispatches[0].method).toBe("POST");
    expect(dispatches[0].headers.get("Authorization")).toBe("Bearer gh-test-token");
    expect(dispatches[0].headers.get("User-Agent")).toBeTruthy();
    expect(JSON.parse(dispatches[0].body!)).toEqual({
      event_type: "review-decision", client_payload: { event_id: event.id, deal_id: 7, type: "approve" } });
    expect(body).toMatchObject({ ok: true, dispatched: true, event_id: event.id });
    expect(body.message).toContain("58 €");
  });

  it("refuses with the pt-PT reason when the price moved, writing nothing", async () => {
    const w = await world();
    w.net.on(PRICES, () => Response.json(pricesPayload(item(70))));
    const { res, body } = await decide(w, { type: "approve", deal_id: 7 });
    expect(res.status).toBe(409);
    expect(body.message).toBe("O preço mudou (o preço subiu para 70 €): não aprovado. A próxima recolha expira o deal.");
    expect(body.check).toMatchObject({ valid: false, price_eur: 70 });
    expect(w.store.keys(PENDING)).toEqual([]);
    expect(w.net.to(DISPATCH)).toHaveLength(0);
  });

  it("refuses when the provider can't be asked", async () => {
    const w = await world();
    w.net.on(PRICES, () => new Response("boom", { status: 502 }));
    const { res, body } = await decide(w, { type: "approve", deal_id: 7 });
    expect(res.status).toBe(502);
    expect(body.message).toBe("Não foi possível verificar o preço agora: o Travelpayouts respondeu com o erro HTTP 502.");
    expect(body.message).not.toContain("boom");
    expect(w.store.keys(PENDING)).toEqual([]);
    expect(w.net.to(DISPATCH)).toHaveLength(0);
  });

  it.each([
    ["an approved deal", 5, "Não é possível passar de 'aprovado' para 'aprovado'."],
    ["a deal not rendered yet", 6, "Não é possível passar de 'novo' para 'aprovado'."],
  ])("refuses %s before asking the provider", async (_, id, message) => {
    const w = await world();
    const { res, body } = await decide(w, { type: "approve", deal_id: id });
    expect(res.status).toBe(409);
    expect(body.message).toBe(message);
    expect(w.net.to(PRICES)).toHaveLength(0);
    expect(w.store.keys(PENDING)).toEqual([]);
  });

  it("refuses a deal without an affiliate link", async () => {
    const w = await world(snapshot({ queue: [deal(7, { affiliate_url: null, affiliate_error: "HTTP 500" })] }));
    const { res, body } = await decide(w, { type: "approve", deal_id: 7 });
    expect(res.status).toBe(409);
    expect(body.message).toBe("Este deal ainda não tem link de afiliado. Volta a renderizar.");
  });
});

describe("reject and published", () => {
  it("writes a reject event without a live check", async () => {
    const w = await world();
    const { res } = await decide(w, { type: "reject", deal_id: 7, note: "" });
    expect(res.status).toBe(200);
    const [key] = w.store.keys(PENDING);
    const event = w.store.json(key);
    expect(schemaErrors("event", event)).toEqual([]);
    expect(event).toMatchObject({ type: "reject", deal_id: 7, actor: EMAIL, note: null, post_url: null, live_check: null });
    expect(w.net.to(PRICES)).toHaveLength(0);
    expect(w.net.to(DISPATCH)).toHaveLength(1);
  });

  it("marks an approved deal as published with the post link", async () => {
    const w = await world();
    const url = "https://www.instagram.com/p/abc123/";
    const { res } = await decide(w, { type: "published", deal_id: 5, post_url: url, note: "ignorada" });
    expect(res.status).toBe(200);
    const event = w.store.json(w.store.keys(PENDING)[0]);
    expect(schemaErrors("event", event)).toEqual([]);
    expect(event).toMatchObject({ type: "published", deal_id: 5, post_url: url, note: null, live_check: null });
  });

  it("refuses a post link that isn't http(s)", async () => {
    const w = await world();
    const { res, body } = await decide(w, { type: "published", deal_id: 5, post_url: "instagram.com/p/x" });
    expect(res.status).toBe(409);
    expect(body.message).toBe("O link do post tem de começar por https://");
    expect(w.store.keys(PENDING)).toEqual([]);
  });

  it("refuses publishing a deal still in the queue", async () => {
    const w = await world();
    const { res, body } = await decide(w, { type: "published", deal_id: 7 });
    expect(res.status).toBe(409);
    expect(body.message).toBe("Não é possível passar de 'por rever' para 'publicado'.");
  });
});

describe("dispatch", () => {
  it.each([
    ["GitHub refuses", () => new Response('{"message":"Bad credentials"}', { status: 401 }),
      "O aviso ao GitHub falhou (o GitHub respondeu com o erro HTTP 401)"],
    ["GitHub is unreachable", () => { throw new TypeError("network down"); },
      "O aviso ao GitHub falhou (o GitHub não respondeu)"],
  ])("keeps the event and says so when %s", async (_, route, reason) => {
    const w = await world();
    w.net.on(DISPATCH, route as any);
    const { res, body } = await decide(w, { type: "reject", deal_id: 7 });
    expect(res.status).toBe(200);
    expect(body).toMatchObject({ ok: true, dispatched: false });
    expect(body.message).toContain(`${reason}: a decisão ficou guardada; aplica-se no próximo run`);
    expect(body.message).not.toMatch(/Bad credentials|network down/);
    expect(w.store.keys(PENDING)).toHaveLength(1);
    expect(w.net.to(DISPATCH)).toHaveLength(1);         // one attempt, no retry storm
  });

  it("doesn't dispatch when the event could not be stored", async () => {
    const w = await world();
    w.store.failPuts = true;
    const { res, body } = await decide(w, { type: "reject", deal_id: 7 });
    expect(res.status).toBe(500);
    expect(body.message).toMatch(/^Não foi possível guardar a decisão/);
    expect(w.net.to(DISPATCH)).toHaveLength(0);
  });
});

describe("pending decisions", () => {
  const pendingEvent = (id: string, created: string, dealId = 7) => ({
    version: 1, id, type: "reject", deal_id: dealId, created_at: created, actor: "cli:miguel@DESKTOP",
    note: null, post_url: null, live_check: null,
  });

  it("refuses a second decision while the snapshot lists one for the deal", async () => {
    const e = pendingEvent("11111111-1111-4111-8111-111111111111", "2026-10-14T08:00:00Z");
    const w = await world(snapshot({ pending_events: [e] }));
    const { res, body } = await decide(w, { type: "approve", deal_id: 7 });
    expect(res.status).toBe(409);
    expect(body.message).toBe("Já há uma decisão pendente para o deal 7 (rejeitar, cli:miguel@DESKTOP): é aplicada na próxima execução.");
    expect(w.net.to(PRICES)).toHaveLength(0);
  });

  it("also counts events written after the snapshot, and only those", async () => {
    const w = await world();
    // Applied by the run that wrote the snapshot (kept pending until the next run, D26): no block.
    const applied = pendingEvent("22222222-2222-4222-8222-222222222222", "2026-10-14T08:15:00Z");
    w.store.putJson(`${PENDING}20261014T081500Z-${applied.id}.json`, applied);
    expect((await decide(w, { type: "reject", deal_id: 7 })).res.status).toBe(200);
    // That decision is newer than the snapshot: the next one waits for it.
    const { res, body } = await decide(w, { type: "approve", deal_id: 7 });
    expect(res.status).toBe(409);
    expect(body.message).toContain(`(rejeitar, ${EMAIL})`);
    expect(w.store.keys(PENDING)).toHaveLength(2);
  });
});

describe("live check without deciding", () => {
  it("answers the check and writes nothing", async () => {
    const w = await world();
    const res = await handle(post("/review/check", { deal_id: 5 }, w.token), w.env, w.deps);
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ ok: true, check: { valid: true, price_eur: 58, reason: "continua a 58 €" } });
    expect(w.store.keys(PENDING)).toEqual([]);
    expect(w.net.to(DISPATCH)).toHaveLength(0);
  });

  it("doesn't check closed deals", async () => {
    const w = await world(snapshot({ closed: [deal(3, { status: "expired", status_pt: "expirado" })] }));
    const res = await handle(post("/review/check", { deal_id: 3 }, w.token), w.env, w.deps);
    expect(res.status).toBe(409);
    expect((await res.json() as any).message).toBe("O deal 3 está 'expirado' e já não é verificado.");
  });
});

describe("requests the Function refuses", () => {
  it("answers 404 for a deal the snapshot doesn't have", async () => {
    const w = await world();
    const { res, body } = await decide(w, { type: "reject", deal_id: 99 });
    expect(res.status).toBe(404);
    expect(body.message).toMatch(/^O deal 99 não está na fila/);
  });

  it.each([
    [{ type: "delete", deal_id: 7 }, "Decisão desconhecida: 'delete'."],
    [{ type: "reject", deal_id: "7" }, "Pedido inválido: falta o número do deal."],
  ])("rejects a malformed body %j", async (payload, message) => {
    const w = await world();
    const { res, body } = await decide(w, payload);
    expect(res.status).toBe(400);
    expect(body.message).toBe(message);
  });

  it("refuses an unknown decision before reading the store", async () => {
    for (const [snap, id] of [[undefined, 99], [null, 7]] as const) {
      const w = await world(snap);
      const { res, body } = await decide(w, { type: "delete", deal_id: id });
      expect(res.status).toBe(400);
      expect(body.message).toBe("Decisão desconhecida: 'delete'.");
    }
  });

  it("refuses posts from another site (CSRF) and non-JSON bodies", async () => {
    const w = await world();
    expect((await decide(w, { type: "reject", deal_id: 7 }, { Origin: "https://evil.example" })).res.status).toBe(403);
    const form = await handle(post("/review/decision", "type=reject", w.token, { "Content-Type": "application/x-www-form-urlencoded" }), w.env, w.deps);
    expect(form.status).toBe(415);
    expect(w.store.keys(PENDING)).toEqual([]);
  });

  it("says so when there is no snapshot yet", async () => {
    const w = await world(null);
    const { res, body } = await decide(w, { type: "reject", deal_id: 7 });
    expect(res.status).toBe(503);
    expect(body.message).toContain("snapshot");
  });

  it("answers 405 to a GET on an action and 404 to unknown paths", async () => {
    const w = await world();
    const { get } = await import("./helpers");
    expect((await handle(get("/review/decision", w.token), w.env, w.deps)).status).toBe(405);
    expect((await handle(get("/review/nada", w.token), w.env, w.deps)).status).toBe(404);
  });
});

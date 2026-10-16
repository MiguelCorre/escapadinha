// The queue page Miguel opens on his phone (#9, D29): server-rendered from the snapshot, pt-PT,
// noindex, never cached, one column at 375 px.
import { parse, type HTMLElement } from "node-html-parser";
import { describe, expect, it } from "vitest";
import { handle } from "../../functions/_lib/review/handler";
import { TOKENS } from "../../src/lib/tokens";
import { deal, get, post, schemaErrors, snapshot, world } from "./helpers";

async function open(snap: Record<string, any> | null = snapshot(), setup?: (w: Awaited<ReturnType<typeof world>>) => void) {
  const w = await world(snap);
  setup?.(w);
  const res = await handle(get("/review", w.token), w.env, w.deps);
  const html = await res.text();
  return { res, html, doc: parse(html), w };
}

const txt = (el: HTMLElement | null) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();

describe("queue page", () => {
  it("is a private pt-PT page for phones", async () => {
    const { res, doc } = await open();
    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(res.headers.get("X-Robots-Tag")).toContain("noindex");
    expect(doc.querySelector("html")!.getAttribute("lang")).toBe("pt-PT");
    expect(doc.querySelector('meta[name="robots"]')!.getAttribute("content")).toContain("noindex");
    expect(doc.querySelector('meta[name="viewport"]')!.getAttribute("content")).toContain("width=device-width");
    expect(txt(doc.querySelector("title"))).toBe("Fila de aprovação · Ponto Nómada");
  });

  it("shows everything Miguel decides on, per candidate", async () => {
    const { doc } = await open();
    const card = doc.querySelector('[data-deal="7"]')!;
    expect(card.getAttribute("data-obs")).toBe("1007");
    const t = txt(card);
    for (const piece of ["Lisboa → Londres (Gatwick)", "58 €", "20 a 23 de novembro · 3 noites", "TAP Air Portugal",
      "voos diretos", "Gatwick", "−44% vs. mínimo habitual 104 € (21 dias em 24, de 89 € a 131 €)",
      "encontrado a 14/10/2026",
      "verificado a 14/10/2026 às 09:17", "por rever", "só bagagem de mão", "Kiwi.com"]) {
      expect(t).toContain(piece);
    }
    const unknown = txt(doc.querySelector('[data-deal="6"]'));          // no GraphQL match (D43)
    expect(unknown).not.toContain("Bagagem");
    expect(unknown).not.toContain("Agência");
    expect(card.querySelectorAll("img").map((i) => i.getAttribute("src")))
      .toEqual(["/review/slides/7/slide_01.webp", "/review/slides/7/slide_02.webp"]);
    const actions = card.querySelectorAll("button[data-act]").map((b) => b.getAttribute("data-act"));
    expect(actions).toEqual(expect.arrayContaining(["check", "approve", "reject"]));
    expect(txt(card.querySelector('button[data-act="check"]'))).toBe("Verificar preço");
    expect(card.querySelector("[data-result]")).not.toBeNull();
  });

  it("shows how solid the typical low is, each extreme daily low on its observation (D40)", async () => {
    const baseline = { span_days: 11, lowest_eur: 54, lowest_observation_id: 2001, highest_eur: 110.5,
      highest_observation_id: 2002 };
    const snap = snapshot({ queue: [deal(7, { typical_low_eur: 99, baseline_days: 10, discount_pct: 41, baseline })] });
    expect(schemaErrors("snapshot", snap)).toEqual([]);
    const { doc } = await open(snap);
    const card = doc.querySelector('[data-deal="7"]')!;
    expect(txt(card)).toContain("−41% vs. mínimo habitual 99 € (10 dias em 12, de 54 € a 110,50 €)");
    expect(txt(card.querySelector('[data-obs="2001"]'))).toBe("54 €");
    expect(txt(card.querySelector('[data-obs="2002"]'))).toBe("110,50 €");
  });

  it("shows only the days for a deal without a stored range or from an older snapshot", async () => {
    const { baseline: _, ...before } = deal(7);                     // a snapshot made before D40
    const older = snapshot({ queue: [before] });
    expect(schemaErrors("snapshot", snapshot())).toEqual([]);
    expect(schemaErrors("snapshot", older)).toEqual([]);
    const none = snapshot({ queue: [deal(7, { baseline: null })] });
    expect(schemaErrors("snapshot", none)).toEqual([]);
    for (const snap of [older, none]) {
      const { doc } = await open(snap);
      expect(txt(doc.querySelector('[data-deal="7"]'))).toContain("−44% vs. mínimo habitual 104 € (21 dias)");
    }
  });

  it("reads the snapshot as is, never against the schema, so a newer snapshot's keys don't break it", async () => {
    // Optional snapshot fields join v1 (D29's transfers, D40's baseline) only because the Function
    // never validates the snapshot at run time: the schema before such a field refuses a snapshot
    // that has it (additionalProperties: false), and an older Function must still serve it.
    const snap = snapshot({ queue: [deal(7, { added_later: { days: 3 } })], added_later: true });
    expect(schemaErrors("snapshot", snap)).not.toEqual([]);
    const { res, doc, w } = await open(snap);
    expect(res.status).toBe(200);
    expect(txt(doc.querySelector('[data-deal="7"]'))).toContain("Lisboa → Londres (Gatwick)");
    const decided = await handle(post("/review/decision", { type: "reject", deal_id: 7 }, w.token), w.env, w.deps);
    expect(decided.status).toBe(200);
    expect(w.store.keys("review/events/pending/")).toHaveLength(1);
  });

  it("offers only what the deal's status allows", async () => {
    const { doc } = await open();
    const fresh = doc.querySelector('[data-deal="6"]')!;                  // new: not rendered yet
    expect(fresh.querySelector('button[data-act="approve"]')).toBeNull();
    expect(txt(fresh)).toContain("Sem slides");
    const approved = doc.querySelector('[data-deal="5"]')!;
    const acts = approved.querySelectorAll("button[data-act]").map((b) => b.getAttribute("data-act"));
    expect(acts).toEqual(expect.arrayContaining(["check", "published", "reject"]));
    expect(acts).not.toContain("approve");
    expect(approved.querySelector('input[name="post_url"]')).not.toBeNull();
    expect(approved.querySelector('a[href="https://pontonomada.pt/promos/5-lisboa-londres/"]')).not.toBeNull();
  });

  it("shows the WhatsApp text with a copy button only when the snapshot has it", async () => {
    const text = "✈️ Lisboa → Londres por 58 €\nhttps://pontonomada.pt/promos/7/";
    const { doc } = await open(snapshot({ queue: [deal(7, { whatsapp_text: text }), deal(8)] }));
    const card = doc.querySelector('[data-deal="7"]')!;
    expect(card.querySelector("[data-whatsapp]")!.textContent).toBe(text);
    expect(card.querySelector('button[data-act="copy-whatsapp"]')).not.toBeNull();
    expect(doc.querySelector('[data-deal="8"] [data-whatsapp]')).toBeNull();
  });

  it("marks deals with a pending decision and offers no second one", async () => {
    const event = { version: 1, id: "11111111-1111-4111-8111-111111111111", type: "approve", deal_id: 7,
      created_at: "2026-10-14T08:00:00Z", actor: "cli:miguel@DESKTOP", note: null, post_url: null,
      live_check: { valid: true, price_eur: 58, reason: "continua a 58 €", checked_at: "2026-10-14T08:00:00Z" } };
    const { doc } = await open(snapshot({ pending_events: [event] }));
    const card = doc.querySelector('[data-deal="7"]')!;
    expect(txt(card)).toContain("Decisão pendente: aprovar (cli:miguel@DESKTOP, 14/10/2026 às 09:00)");
    expect(card.querySelector('button[data-act="approve"]')).toBeNull();
    expect(card.querySelector('button[data-act="reject"]')).toBeNull();
  });

  it("says when the queue was made, by whom it is seen and the approval age rule", async () => {
    const { doc } = await open();
    const t = txt(doc.querySelector("body"));
    expect(t).toContain("Fila de 14/10/2026 às 09:21");
    expect(t).toContain("miguelahpc@hotmail.com");
    expect(t).toContain("mais de 24 h");
  });

  it("lists refused decisions with their reason", async () => {
    const outcome = { event_id: "x", type: "approve", deal_id: 4, actor: "miguelahpc@hotmail.com", outcome: "refused",
      reason: "Aprovação com mais de 24 h: verifica o preço outra vez.", settled_at: "2026-10-14T08:17:00Z",
      status_before: "rendered", status_after: "rendered" };
    const { doc } = await open(snapshot({ recent_outcomes: [outcome] }));
    expect(txt(doc.querySelector("body"))).toContain("Aprovação com mais de 24 h: verifica o preço outra vez.");
  });

  it("uses public slide URLs when a deal has no store copy", async () => {
    const slides = [{ url: "https://pontonomada.pt/img/promos/5/slide_01.webp", key: null }];
    const { doc } = await open(snapshot({ approved: [deal(5, { status: "approved", status_pt: "aprovado", slides })] }));
    expect(doc.querySelector('[data-deal="5"] img')!.getAttribute("src")).toBe(slides[0].url);
  });

  it("escapes snapshot text", async () => {
    const { html } = await open(snapshot({ queue: [deal(7, { headline: "<script>alert(1)</script>", caption: "</pre><b>x" })] }));
    expect(html).not.toContain("<script>alert(1)");
    expect(html).not.toContain("<b>x");
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
  });

  it("explains an empty queue and a missing snapshot", async () => {
    const empty = await open(snapshot({ queue: [], approved: [] }));
    expect(txt(empty.doc.querySelector("body"))).toContain("Nenhum deal por rever");
    const none = await open(null);
    expect(none.res.status).toBe(200);
    expect(txt(none.doc.querySelector("body"))).toContain("Ainda não há snapshot");
  });

  it("warns when the snapshot is old (the pipeline may be stopped)", async () => {
    const { doc } = await open(snapshot({ generated_at: "2026-10-14T03:00:00Z" }));
    expect(txt(doc.querySelector("body"))).toContain("A fila tem mais de 3 h");
  });

  it("fits a 375 px screen: one column, nothing wider than the viewport", async () => {
    const { html } = await open();
    const css = html.match(/<style>([\s\S]*?)<\/style>/)![1];
    const widths = [...css.matchAll(/(?:^|[^-])(?:min-)?width:\s*(\d+)px/g)].map((m) => Number(m[1]));
    expect(widths.every((w) => w <= 343)).toBe(true);           // 375 - 2 × 16 px gutter
    expect(css).toMatch(/overflow-wrap:\s*anywhere/);
  });

  it("uses the design system's tokens: both palettes, square cards, ink input borders", async () => {
    const { html } = await open();
    const css = html.match(/<style>([\s\S]*?)<\/style>/)![1];
    for (const [name, value] of Object.entries(TOKENS.themes.light)) expect(css).toContain(`--pn-${name}: ${value};`);
    const dark = css.match(/prefers-color-scheme: dark\) \{ :root \{([^}]*)\}/)![1];
    for (const [name, value] of Object.entries(TOKENS.themes.dark)) expect(dark).toContain(`--pn-${name}: ${value};`);
    // Every colour is a token variable; anything a user must see (input borders) is ink (§2).
    expect(css.replace(/--pn-[\w-]+: #[0-9A-F]{6};/g, "")).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(css).toMatch(/\.actions input \{[^}]*border-radius: 4px; border: 1px solid var\(--pn-ink\)/);
    expect(css).toMatch(/\.card \{[^}]*border-radius: 0;/);
    expect(css).toContain(`box-shadow: ${TOKENS.boxShadow.focus}`);
  });
});

describe("slides", () => {
  it("streams a queue slide from the store", async () => {
    const w = await world();
    w.store.objects.set("review/slides/7/slide_01.webp", new TextEncoder().encode("RIFF....WEBP"));
    const res = await handle(get("/review/slides/7/slide_01.webp", w.token), w.env, w.deps);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("image/webp");
    expect(res.headers.get("Cache-Control")).toMatch(/^private/);
    expect(await res.text()).toBe("RIFF....WEBP");
  });

  it("answers 404 for a missing slide and never reads outside review/slides/", async () => {
    const w = await world();
    for (const path of ["/review/slides/7/slide_09.webp", "/review/slides/7/..%2Fsnapshot.json",
      "/review/slides/../snapshot.json", "/review/slides/7/slide_01.png"]) {
      expect((await handle(get(path, w.token), w.env, w.deps)).status, path).toBe(404);
    }
  });
});

// The queue page (#9, D29), server-rendered from review/snapshot.json. Same information and copy
// as the local review page (src/escapadinha/templates/review.html.j2), laid out for a phone:
// one column, slides in a swipeable strip, big buttons. A small script posts the decisions as
// JSON to /review/decision and /review/check and shows the answer in the card.
import { BRAND } from "../../../src/lib/brand";
import { discountPercent, eur, lisbonTimestamp } from "../../../src/lib/format";
import { TOKENS } from "../../../src/lib/tokens";
import { DECISION_PT } from "./rules";
import type { Outcome, ReviewEvent, Snapshot, SnapshotDeal } from "./types";

const STALE_HOURS = 3;   // runs every 2 h (D25): older than this, something is wrong

const ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

const row = (label: string, value: string) => (value ? `<dt>${esc(label)}</dt><dd>${value}</dd>` : "");

const link = (href: string, label: string) =>
  `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;

function slides(d: SnapshotDeal): string {
  const items = d.slides
    .map((s, i) => {
      const src = s.key ? `/review/${s.key.slice("review/".length)}` : s.url;
      return src ? `<a href="${esc(src)}" target="_blank" rel="noopener"><img src="${esc(src)}" alt="Slide ${i + 1}" loading="lazy" width="270" height="338"></a>` : "";
    })
    .join("");
  return `<div class="slides">${items || `<p class="none">Sem slides (ainda não renderizado)</p>`}</div>`;
}

/** A price traced to its observation (D2). */
const obsPrice = (id: number, amount: number) => `<span data-obs="${esc(id)}">${esc(eur(amount))}</span>`;

/** The discount line (HTML): the typical low with its days in their window (first to last day)
 * and its cheapest and dearest daily low (D40). Without a stored range (an older deal or
 * snapshot) the days only, as the local page. */
function dealLine(d: SnapshotDeal): string {
  if (d.rule === "median" && d.discount_pct) {
    const typical = d.typical_low_eur === null ? "" : ` ${eur(d.typical_low_eur)}`;
    const b = d.baseline;
    const lows = b
      ? `${d.baseline_days} dias em ${b.span_days + 1}, de ${obsPrice(b.lowest_observation_id, b.lowest_eur)}`
        + ` a ${obsPrice(b.highest_observation_id, b.highest_eur)}`
      : `${d.baseline_days} dias`;
    return `${esc(discountPercent(d.discount_pct))} vs. mínimo habitual${esc(typical)} (${lows})`;
  }
  return d.rule === "price_cap" ? "abaixo do teto de preço da rota" : "";
}

function copyBlock(label: string, attr: string, act: string, button: string, body: string, open = false): string {
  return `<details${open ? " open" : ""}><summary>${esc(label)}</summary><pre class="copy" ${attr}>${esc(body)}</pre>`
    + `<button type="button" class="btn" data-act="${act}">${esc(button)}</button></details>`;
}

function card(d: SnapshotDeal, pending: ReviewEvent[], approveHours: number): string {
  const mine = pending.filter((e) => e.deal_id === d.id);
  const flights = [d.airline, d.direct === true ? "voos diretos" : d.direct === false ? "com escala" : ""]
    .filter(Boolean).join(" · ");
  const lc = d.live_check;
  const lastCheck = lc.last_checked_at
    ? lisbonTimestamp(lc.last_checked_at) + (lc.last_seen_price_eur === null ? "" : ` · ${eur(lc.last_seen_price_eur)}`)
    : "";
  const affiliate = d.affiliate_url
    ? link(d.affiliate_url, d.affiliate_url)
    : `<span class="bad">sem link (${esc(d.affiliate_error || "não gerado")})</span>`;

  const notes: string[] = [];
  for (const e of mine) {
    notes.push(`<p class="notice warn">Decisão pendente: ${esc(DECISION_PT[e.type])} (${esc(e.actor)}, `
      + `${esc(lisbonTimestamp(e.created_at))}). É aplicada na próxima execução.</p>`);
  }
  if (d.status === "expired") notes.push(`<p class="notice bad">Expirado: ${esc(lc.expired_reason)}. Não publicar.</p>`);
  if (d.status === "approved") {
    notes.push(`<p class="notice ok">Aprovado. Publica depressa: o preço é verificado de 2 em 2 horas e o deal expira se mudar.</p>`);
  }
  if (d.status === "new") notes.push(`<p class="notice warn">Ainda não renderizado: aprova depois de a próxima execução gerar os slides.</p>`);
  if (d.review_note) notes.push(`<p class="notice warn">Nota: ${esc(d.review_note)}</p>`);

  const btn = (act: string, label: string, cls = "") =>
    `<button type="button" class="btn ${cls}" data-act="${act}">${esc(label)}</button>`;
  const open = d.status === "new" || d.status === "rendered" || d.status === "approved";
  let actions = "";
  if (open && !mine.length) {
    if (d.status === "approved") {
      actions = `<input name="post_url" type="url" inputmode="url" placeholder="Link do post no Instagram (opcional)" aria-label="Link do post">`
        + btn("check", "Verificar preço") + btn("published", "Marcar como publicado", "primary") + btn("reject", "Rejeitar", "danger");
    } else {
      actions = `<input name="note" placeholder="Nota (opcional)" aria-label="Nota">` + btn("check", "Verificar preço")
        + (d.status === "rendered" ? btn("approve", "Aprovar", "primary") : "") + btn("reject", "Rejeitar", "danger");
    }
  } else if (open) {
    actions = btn("check", "Verificar preço");
  }
  if (d.affiliate_url) actions += btn("copy-link", "Copiar link");

  const extras = [
    d.whatsapp_text ? copyBlock("Texto para o WhatsApp", "data-whatsapp", "copy-whatsapp", "Copiar texto do WhatsApp", d.whatsapp_text, true) : "",
    d.caption ? copyBlock("Legenda do Instagram", "data-caption", "copy-caption", "Copiar legenda", d.caption) : "",
  ].join("");

  return `<article class="card" id="deal-${d.id}" data-deal="${d.id}" data-obs="${d.observation_id}"
  data-status="${esc(d.status)}" data-link="${esc(d.affiliate_url ?? "")}">
  ${slides(d)}
  <div class="info">
    <div class="top">
      <h3 class="headline">${esc(d.headline)}</h3>
      <span class="badge ${esc(d.status)}">${esc(d.status_pt)}</span>
    </div>
    <p class="price">${esc(d.price)} <small>ida e volta</small></p>
    ${notes.join("")}
    <dl>
      ${row("Datas", esc(`${d.dates} · ${d.nights}`))}
      ${row("Voos", esc(flights))}
      ${row("Chegada", esc(d.arrival_airport))}
      ${row("Desconto", dealLine(d))}
      ${row("Preço visto", esc([d.found_on && `encontrado a ${d.found_on}`, `verificado a ${d.checked_at}`].filter(Boolean).join(" · ")))}
      ${row("Última verificação", esc(lastCheck))}
      ${row("Link", affiliate)}
      ${row("Página", d.page_url ? link(d.page_url, d.page_url) : "")}
      ${row("Publicado", d.published_at ? esc(lisbonTimestamp(d.published_at)) + (d.post_url ? ` · ${link(d.post_url, "ver post")}` : "") : "")}
    </dl>
    ${extras}
    <p class="notice" data-result role="status" hidden></p>
    ${actions ? `<div class="actions">${actions}</div>` : ""}
    ${d.status === "rendered" && !mine.length ? `<p class="hint">Aprovar verifica o preço na hora. A aprovação vale ${approveHours} h: se o pipeline só a aplicar mais tarde, recusa-a e tens de aprovar outra vez.</p>` : ""}
  </div>
</article>`;
}

function compact(d: SnapshotDeal): string {
  const why = d.status === "expired" && d.live_check.expired_reason ? ` · ${d.live_check.expired_reason}` : "";
  return `<li data-deal="${d.id}" data-obs="${d.observation_id}"><strong>${esc(d.headline)}</strong> · ${esc(d.price)} · `
    + `${esc(d.dates)} · ${esc(d.status_pt)}${esc(why)}${d.post_url ? ` · ${link(d.post_url, "ver post")}` : ""}</li>`;
}

function outcome(o: Outcome): string {
  const what = o.type ? DECISION_PT[o.type] : "evento";
  const verdict = o.outcome === "applied" ? "aplicada" : o.outcome === "refused" ? "recusada" : "inválida";
  return `<li class="${o.outcome === "applied" ? "ok" : "bad"}">${esc(lisbonTimestamp(o.settled_at))} · `
    + `${esc(what)} o deal ${esc(o.deal_id ?? "?")} (${esc(o.actor ?? "?")}): ${verdict}${o.reason ? `: ${esc(o.reason)}` : ""}</li>`;
}

function section(id: string, title: string, deals: SnapshotDeal[], body: string, empty: string): string {
  return `<section aria-labelledby="${id}"><h2 id="${id}">${esc(title)} <span class="count">${deals.length}</span></h2>`
    + (deals.length ? body : `<p class="empty">${esc(empty)}</p>`) + `</section>`;
}

// The design system's palette, radii and focus ring (docs/design/design-system.md §2–§4), from
// the generated TOKENS (src/lib/tokens.ts, `npm run tokens`): no colour of its own. The web
// fonts aren't served to the Function, so the text stack falls back to Georgia.
const palette = (theme: Record<string, string>) =>
  Object.entries(theme).map(([name, value]) => `--pn-${name}: ${value};`).join(" ");
const stack = (fonts: readonly string[]) => fonts.map((f) => (/\s/.test(f) ? `"${f}"` : f)).join(", ");
const { borderRadius: radius, boxShadow: shadow } = TOKENS;

const CSS = `
:root { color-scheme: light dark; ${palette(TOKENS.themes.light)} }
@media (prefers-color-scheme: dark) { :root { ${palette(TOKENS.themes.dark)} } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--pn-bg); color: var(--pn-ink); font: 16px/1.45 ${stack(TOKENS.fontFamily.text)}; }
header, main, footer { max-width: 680px; margin: 0 auto; padding: 0 16px; }
header { padding-top: 16px; }
h1 { margin: 0; font-size: 21px; }
h2 { font-size: 17px; margin: 28px 0 10px; }
.count { display: inline-block; min-width: 24px; padding: 0 7px; border-radius: ${radius.sm}; background: var(--pn-rule); font-size: 13px; text-align: center; }
.meta { color: var(--pn-muted); font-size: 14px; margin: 4px 0 0; overflow-wrap: anywhere; }
.card { background: var(--pn-surface); border: 1px solid var(--pn-rule); border-top: 3px double var(--pn-ink); border-radius: ${radius.none}; overflow: hidden; margin-bottom: 16px; }
.slides { display: flex; gap: 8px; overflow-x: auto; scroll-snap-type: x mandatory; padding: 10px; background: var(--pn-bg); }
.slides a { flex: 0 0 72%; scroll-snap-align: start; border-radius: ${radius.none}; overflow: hidden; background: var(--pn-rule); }
.slides img { display: block; width: 100%; height: auto; aspect-ratio: 4 / 5; object-fit: cover; }
.slides .none { margin: 0; padding: 24px 8px; color: var(--pn-muted); width: 100%; text-align: center; }
.info { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
.headline { margin: 0; font-size: 18px; overflow-wrap: anywhere; }
.price { margin: 0; font-size: 26px; font-weight: 800; }
.price small { font-size: 14px; font-weight: 600; color: var(--pn-muted); }
.badge { font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: ${radius.sm}; white-space: nowrap; background: var(--pn-rule); }
.badge.approved, .badge.published { background: var(--pn-success-bg); color: var(--pn-success); }
.badge.expired, .badge.rejected { background: var(--pn-expired-bg); color: var(--pn-expired); }
.badge.rendered, .badge.new { background: var(--pn-warning-bg); color: var(--pn-warning); }
dl { margin: 0; display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 12px; font-size: 14px; }
dt { color: var(--pn-muted); }
dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
a { color: var(--pn-accent); overflow-wrap: anywhere; }
:focus-visible { outline: none; box-shadow: ${shadow.focus}; }
.bad { color: var(--pn-expired); }
.notice { margin: 0; padding: 9px 12px; border-left: 6px solid var(--pn-rule); font-size: 14px; overflow-wrap: anywhere; }
.notice.ok { border-color: var(--pn-success); background: var(--pn-success-bg); color: var(--pn-ink); }
.notice.bad { border-color: var(--pn-expired); background: var(--pn-expired-bg); color: var(--pn-ink); }
.notice.warn { border-color: var(--pn-warning); background: var(--pn-warning-bg); color: var(--pn-ink); }
details summary { cursor: pointer; color: var(--pn-muted); font-size: 14px; padding: 4px 0; }
pre.copy { white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.5 ${stack(TOKENS.fontFamily.text)}; background: var(--pn-bg);
  border-radius: ${radius.none}; padding: 10px 12px; margin: 6px 0 8px; max-height: 260px; overflow: auto; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.actions input { flex: 1 1 100%; min-width: 0; padding: 11px 12px; border-radius: ${radius.md}; border: 1px solid var(--pn-ink);
  background: var(--pn-surface); color: var(--pn-ink); font: inherit; }
.btn { flex: 1 1 auto; min-height: 44px; border: 1px solid var(--pn-ink); background: var(--pn-surface); color: var(--pn-ink);
  font: inherit; font-weight: 600; letter-spacing: 0.04em; padding: 10px 14px; border-radius: ${radius.none}; cursor: pointer; }
.btn.primary { background: var(--pn-accent); border-color: var(--pn-accent); color: var(--pn-on-accent); }
.btn.danger { color: var(--pn-expired); border-color: var(--pn-expired); }
.btn:disabled { opacity: .55; cursor: progress; }
.hint { margin: 0; color: var(--pn-muted); font-size: 13px; }
.empty { color: var(--pn-muted); }
ul.list { padding-left: 18px; margin: 0; font-size: 14px; display: grid; gap: 6px; overflow-wrap: anywhere; }
ul.list .ok { color: var(--pn-success); } ul.list .bad { color: var(--pn-expired); }
footer { color: var(--pn-muted); font-size: 13px; padding-bottom: 40px; }
`;

const SCRIPT = `
const say = (card, kind, text) => { const p = card.querySelector("[data-result]");
  p.className = "notice " + kind; p.textContent = text; p.hidden = false; };
async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body), credentials: "same-origin" });
  let data = {};
  try { data = await res.json(); } catch (e) { data = { message: "Resposta inesperada (HTTP " + res.status + "). Volta a abrir a página." }; }
  return { res, data };
}
async function copy(card, text, done) {
  try { await navigator.clipboard.writeText(text); say(card, "ok", done); }
  catch (e) { say(card, "bad", "Não foi possível copiar: seleciona o texto à mão."); }
}
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-act]"); if (!b) return;
  const card = b.closest("[data-deal]"); const id = Number(card.dataset.deal); const act = b.dataset.act;
  if (act === "copy-whatsapp") return copy(card, card.querySelector("[data-whatsapp]").textContent, "Texto do WhatsApp copiado.");
  if (act === "copy-caption") return copy(card, card.querySelector("[data-caption]").textContent, "Legenda copiada.");
  if (act === "copy-link") return copy(card, card.dataset.link, "Link copiado.");
  if (act === "reject" && !confirm("Rejeitar este deal?")) return;
  const buttons = card.querySelectorAll(".actions button"); buttons.forEach((x) => x.disabled = true);
  const label = b.textContent; b.textContent = act === "check" || act === "approve" ? "A verificar preço…" : "A registar…";
  try {
    if (act === "check") {
      const { res, data } = await post("/review/check", { deal_id: id });
      say(card, res.ok && data.check && data.check.valid ? "ok" : "bad", data.message || "Erro");
      buttons.forEach((x) => x.disabled = false);
    } else {
      const field = card.querySelector(act === "published" ? "input[name=post_url]" : "input[name=note]");
      const value = field ? field.value.trim() || null : null;
      const body = { type: act, deal_id: id, ...(act === "published" ? { post_url: value } : { note: value }) };
      const { res, data } = await post("/review/decision", body);
      if (res.ok) { say(card, data.dispatched ? "ok" : "warn", data.message); card.querySelector(".actions").remove(); }
      else { say(card, "bad", data.message || "Erro"); buttons.forEach((x) => x.disabled = false); }
    }
  } catch (e) {
    say(card, "bad", "Sem ligação: verifica a rede e tenta outra vez."); buttons.forEach((x) => x.disabled = false);
  } finally { b.textContent = label; }
});
`;

export function renderPage(snapshot: Snapshot | null, { actor, pending, now }: { actor: string; pending: ReviewEvent[]; now: Date }): string {
  let header = `<p class="meta">Entraste como ${esc(actor)}.</p>`;
  let main: string;
  let footer = "";
  if (!snapshot) {
    main = `<p class="notice warn">Ainda não há snapshot da fila: a próxima execução do pipeline (de 2 em 2 horas) cria-o.</p>`;
  } else {
    const hours = snapshot.review_rules.approve_max_age_hours;
    const age = (now.getTime() - Date.parse(snapshot.generated_at)) / 3_600_000;
    header = `<p class="meta">Fila de ${esc(lisbonTimestamp(snapshot.generated_at))} · entraste como ${esc(actor)}.</p>`
      + (age > STALE_HOURS ? `<p class="notice warn">A fila tem mais de ${STALE_HOURS} h: o pipeline pode estar parado. Vê o separador Actions no GitHub.</p>` : "");
    const cards = (deals: SnapshotDeal[]) => deals.map((d) => card(d, pending, hours)).join("");
    const list = (deals: SnapshotDeal[]) => `<ul class="list">${deals.map(compact).join("")}</ul>`;
    main = [
      section("fila", "Por rever", snapshot.queue, cards(snapshot.queue),
        "Nenhum deal por rever. Os deals novos aparecem aqui depois de cada recolha (de 2 em 2 horas)."),
      section("aprovados", "Aprovados", snapshot.approved, cards(snapshot.approved), "Nenhum deal aprovado à espera de publicação."),
      section("publicados", "Publicados recentemente", snapshot.published, list(snapshot.published), "Ainda nada publicado."),
      section("fechados", "Expirados ou rejeitados", snapshot.closed, list(snapshot.closed), "Nenhum deal expirado ou rejeitado."),
      snapshot.recent_outcomes.length
        ? `<section aria-labelledby="decisoes"><h2 id="decisoes">Decisões recentes</h2><ul class="list">${snapshot.recent_outcomes.map(outcome).join("")}</ul></section>`
        : "",
    ].join("");
    footer = `<footer><p>Uma decisão fica registada logo e o pipeline aplica-a em poucos minutos (ou na execução seguinte, de 2 em 2 horas). `
      + `Uma aprovação com mais de ${hours} h quando for aplicada é recusada: verifica o preço e aprova outra vez.</p></footer>`;
  }
  return `<!doctype html>
<html lang="pt-PT">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Fila de aprovação · ${esc(BRAND)}</title>
<style>${CSS}</style>
</head>
<body>
<header><h1>Fila de aprovação</h1>${header}</header>
<main>${main}</main>
${footer}
<script>${SCRIPT}</script>
</body>
</html>`;
}

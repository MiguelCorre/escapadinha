// The review Function (#9, D29): one pure handler of (request, env, deps) behind every /review
// route; the thin onRequest wrappers in functions/review/ only call it.
//
//   GET  /review                          the queue page, from review/snapshot.json
//   GET  /review/slides/<id>/slide_NN.webp  a queue slide from the store (review/slides/, D26)
//   POST /review/check     {deal_id}       live price check only (writes nothing)
//   POST /review/decision  {type, deal_id, note?, post_url?}
//                                          approve | reject | published -> one pending event
//                                          + one repository_dispatch
//
// Every request needs a valid Cloudflare Access token (access.ts). The Function is a writer of
// pending review events only: it never changes a status (D26).
import { AccessError, HEADER, verifyAccess } from "./access";
import { dispatch, newEvent, pendingEvents, readSnapshot, writeEvent } from "./events";
import { CheckError, liveCheck } from "./live-check";
import { renderPage } from "./page";
import { checkDecision, DECISION_PT, decisionType, OPEN_STATUSES, ReviewError, STATUS_PT } from "./rules";
import type { DecisionType, Deps, Env, LiveCheck, Snapshot, SnapshotDeal } from "./types";

export const DEFAULT_REPOSITORY = "MiguelCorre/escapadinha";
const NO_STORE = { "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow" };
const SLIDE = /^\/review\/slides\/(\d+)\/(slide_\d{2}\.webp)$/;

function text(body: string, status: number): Response {
  return new Response(body, { status, headers: { ...NO_STORE, "Content-Type": "text/plain; charset=utf-8" } });
}

function json(body: Record<string, unknown>, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { ...NO_STORE, "Content-Type": "application/json; charset=utf-8" } });
}

function fail(message: string, status: number, extra: Record<string, unknown> = {}): Response {
  return json({ ok: false, message, ...extra }, status);
}

/** A rule refused the decision (ReviewError, pt-PT); anything else is a bug and propagates. */
function refused(exc: unknown): Response {
  if (exc instanceof ReviewError) return fail(exc.message, exc.status);
  throw exc;
}

function refuse(reason: string): Response {
  return text(`Acesso negado: ${reason}. Abre a fila em https://pontonomada.pt/review e entra com `
    + "o código enviado por e-mail.", 403);
}

function findDeal(snapshot: Snapshot, id: number): SnapshotDeal | undefined {
  return [...snapshot.queue, ...snapshot.approved, ...snapshot.published, ...snapshot.closed]
    .find((d) => d.id === id);
}

/** A same-origin JSON POST: a cross-site form can't send application/json, and a browser
 * always sends Origin on a cross-site fetch. */
async function readBody(request: Request): Promise<Record<string, unknown> | Response> {
  const origin = request.headers.get("Origin");
  if (origin && origin !== new URL(request.url).origin) return fail("Pedido de outro site recusado.", 403);
  if (!(request.headers.get("Content-Type") ?? "").startsWith("application/json")) {
    return fail("Pedido inválido: envia JSON.", 415);
  }
  try {
    const body = await request.json();
    if (body && typeof body === "object" && !Array.isArray(body)) return body as Record<string, unknown>;
  } catch {
    // fall through
  }
  return fail("Pedido inválido: o corpo não é JSON.", 400);
}

const NO_SNAPSHOT = "Ainda não há snapshot da fila (review/snapshot.json): a próxima execução do pipeline cria-o.";

/** The deal a POST is about, from the snapshot; a Response when it can't be decided on. */
async function target(body: Record<string, unknown>, env: Env): Promise<{ snapshot: Snapshot; deal: SnapshotDeal } | Response> {
  const id = body.deal_id;
  if (typeof id !== "number" || !Number.isInteger(id) || id < 1) return fail("Pedido inválido: falta o número do deal.", 400);
  const snapshot = await readSnapshot(env.STORE);
  if (!snapshot) return fail(NO_SNAPSHOT, 503);
  const deal = findDeal(snapshot, id);
  if (!deal) return fail(`O deal ${id} não está na fila (snapshot de ${snapshot.generated_at}).`, 404);
  return { snapshot, deal };
}

async function check(deal: SnapshotDeal, env: Env, deps: Deps): Promise<LiveCheck> {
  return liveCheck(deal, { token: env.TRAVELPAYOUTS_TOKEN, fetch: deps.fetch, now: deps.now });
}

async function onCheck(request: Request, env: Env, deps: Deps): Promise<Response> {
  const body = await readBody(request);
  if (body instanceof Response) return body;
  const found = await target(body, env);
  if (found instanceof Response) return found;
  const { deal } = found;
  if (!OPEN_STATUSES.includes(deal.status)) {
    return fail(`O deal ${deal.id} está '${STATUS_PT[deal.status]}' e já não é verificado.`, 409);
  }
  try {
    const result = await check(deal, env, deps);
    return json({ ok: true, check: result, message: result.valid
      ? `Preço confirmado agora: ${result.reason}.` : `O preço mudou: ${result.reason}.` });
  } catch (exc) {
    if (exc instanceof CheckError) return fail(exc.message, 502);
    throw exc;
  }
}

async function onDecision(request: Request, env: Env, deps: Deps, actor: string): Promise<Response> {
  const body = await readBody(request);
  if (body instanceof Response) return body;
  let kind: DecisionType;
  try {
    kind = decisionType(body.type);           // a malformed request: 400 before any store read
  } catch (exc) {
    return refused(exc);
  }
  const found = await target(body, env);
  if (found instanceof Response) return found;
  const { snapshot, deal } = found;
  const note = kind === "published" || typeof body.note !== "string" ? null : body.note;
  // As given, like pipeline.mark_published (the page trims before sending).
  const postUrl = kind === "published" && typeof body.post_url === "string" ? body.post_url : null;

  // pipeline._decidable: one decision per deal until the pipeline applies it.
  const waiting = (await pendingEvents(env.STORE, snapshot)).filter((e) => e.deal_id === deal.id);
  if (waiting.length) {
    const e = waiting[waiting.length - 1];
    return fail(`Já há uma decisão pendente para o deal ${deal.id} (${DECISION_PT[e.type]}, ${e.actor}): `
      + "é aplicada na próxima execução.", 409);
  }
  try {
    checkDecision(kind, deal.status, { affiliateUrl: deal.affiliate_url, postUrl });
  } catch (exc) {
    return refused(exc);
  }

  // pipeline.approve: the live check is the gate; a moved price writes nothing.
  let live: LiveCheck | null = null;
  if (kind === "approve") {
    try {
      live = await check(deal, env, deps);
    } catch (exc) {
      if (exc instanceof CheckError) return fail(exc.message, 502);
      throw exc;
    }
    if (!live.valid) {
      return fail(`O preço mudou (${live.reason}): não aprovado. A próxima recolha expira o deal.`, 409, { check: live });
    }
  }

  const event = newEvent(kind, deal.id, { id: deps.uuid(), actor, now: deps.now(), note, postUrl, liveCheck: live });
  try {
    await writeEvent(env.STORE, event);
  } catch (exc) {
    return fail(`Não foi possível guardar a decisão: ${(exc as Error).message}. Tenta outra vez.`, 500);
  }
  const problem = await dispatch(event, {
    token: env.GITHUB_DISPATCH_TOKEN, repository: env.GITHUB_REPOSITORY || DEFAULT_REPOSITORY, fetch: deps.fetch });
  const done = kind === "approve" ? `Preço confirmado (${live!.reason}) e aprovação registada.`
    : kind === "reject" ? "Rejeição registada." : "Publicação registada.";
  const message = problem === null
    ? `${done} O pipeline aplica-a dentro de minutos.`
    : `${done} O aviso ao GitHub falhou (${problem}): a decisão ficou guardada; aplica-se no próximo run (até 2 h).`;
  return json({ ok: true, dispatched: problem === null, event_id: event.id, check: live, message });
}

async function onSlide(id: string, name: string, env: Env): Promise<Response> {
  const obj = await env.STORE.get(`review/slides/${id}/${name}`);
  if (!obj) return text("Slide não encontrado.", 404);
  return new Response(obj.body, { headers: {
    "Content-Type": "image/webp", "Cache-Control": "private, max-age=600", "X-Robots-Tag": "noindex, nofollow" } });
}

export async function handle(request: Request, env: Env, deps: Deps): Promise<Response> {
  let actor: string;
  try {
    actor = await verifyAccess(request.headers.get(HEADER),
      { teamDomain: env.ACCESS_TEAM_DOMAIN, aud: env.ACCESS_AUD }, deps);
  } catch (exc) {
    return refuse(exc instanceof AccessError ? exc.message : "não foi possível verificar o acesso agora");
  }

  const path = new URL(request.url).pathname.replace(/\/+$/, "") || "/";
  const method = request.method.toUpperCase();
  const slide = SLIDE.exec(path);
  if (path === "/review") {
    if (method !== "GET" && method !== "HEAD") return text("Método não permitido.", 405);
    const snapshot = await readSnapshot(env.STORE);
    const pending = snapshot ? await pendingEvents(env.STORE, snapshot) : [];
    return new Response(renderPage(snapshot, { actor, pending, now: deps.now() }), {
      headers: { ...NO_STORE, "Content-Type": "text/html; charset=utf-8" } });
  }
  if (slide) {
    if (method !== "GET" && method !== "HEAD") return text("Método não permitido.", 405);
    return onSlide(slide[1], slide[2], env);
  }
  if (path === "/review/check" || path === "/review/decision") {
    if (method !== "POST") return text("Método não permitido.", 405);
    return path === "/review/check" ? onCheck(request, env, deps) : onDecision(request, env, deps, actor);
  }
  return text("Página não encontrada.", 404);
}

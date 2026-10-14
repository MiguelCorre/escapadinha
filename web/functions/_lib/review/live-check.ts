// The approval gate's live price check, ported from the pipeline (D26, D29). The pipeline's
// version is `pipeline.price_now`: one prices_for_dates request for the deal's route-month
// (`collector/travelpayouts.py` request_params + parse_response), then `recheck.recheck`.
// The snapshot gives the exact query and the route rules (`live_check.query` / `.rules`), so the
// only thing ported here is the parsing and the rule. The shared cases in
// contract/review/v1/fixtures/live-check-cases.json run against both sides.
//
// Known differences, both documented in DECISIONS D29:
// - the snapshot doesn't carry the deal's transfer counts, only `direct` (true: none either way);
//   on a route allowing N >= 1 stops a non-direct deal is assumed within the limit (it passed
//   detection under the route's rules; the run's own recheck uses the real counts);
// - no retries on 429/5xx (the pipeline waits up to a minute): the reviewer just tries again.
import { eurPlain, numericDayMonth } from "../../../src/lib/format";
import type { LiveCheck, Rules } from "./types";

export const API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates";

export class CheckError extends Error {}

/** What the check needs from a snapshot deal. */
export interface CheckTarget {
  price_eur: number;
  departure_date: string;
  return_date: string;
  direct: boolean | null;
  live_check: { query: Record<string, string | number>; rules: Rules };
}

interface Offer {
  departure: string;
  return: string;
  price: number;
  transfers: number | null;
  return_transfers: number | null;
  found_date: string | null;
}

export interface Recheck {
  valid: boolean;
  price_eur: number | null;
  reason: string;
}

const DAY_MS = 86_400_000;

const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const dayMs = (isoDate: string) => Date.parse(`${isoDate}T00:00:00Z`);

function nightsBetween(departure: string, ret: string): number {
  return Math.round((dayMs(ret) - dayMs(departure)) / DAY_MS);
}

/** A valid calendar date or null (Python's date(y, m, d) raising ValueError). */
function makeDate(y: number, m: number, d: number): string | null {
  const ms = Date.UTC(y, m - 1, d);
  const dt = new Date(ms);
  if (y < 1 || dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null;
  return iso(ms);
}

/** travelpayouts._near: the date with this day/month within one day of the UTC date. */
function near(day: number, month: number, utcDay: string): string | null {
  const year = Number(utcDay.slice(0, 4));
  for (const y of [year - 1, year, year + 1]) {
    const candidate = makeDate(y, month, day);
    if (candidate && Math.abs(dayMs(candidate) - dayMs(utcDay)) <= DAY_MS) return candidate;
  }
  return null;
}

const LINK_DATES = /^\/search\/[A-Z]{3}(\d{2})(\d{2})[A-Z]{3}(\d{2})(\d{2})\d/;

/** travelpayouts.local_dates: local trip dates from the Aviasales link, else the UTC dates. */
function localDates(link: string | null, departureUtc: string, returnUtc: string): [string, string] {
  const m = LINK_DATES.exec(link ?? "");
  if (!m) return [departureUtc, returnUtc];
  const dep = near(Number(m[1]), Number(m[2]), departureUtc);
  const ret = near(Number(m[3]), Number(m[4]), returnUtc);
  return dep === null || ret === null ? [departureUtc, returnUtc] : [dep, ret];
}

/** travelpayouts.found_date: `search_date=DDMMYYYY` in the link. */
function foundDate(link: string | null): string | null {
  if (!link) return null;
  let value: string | null;
  try {
    value = new URL(link, "https://www.aviasales.pt").searchParams.get("search_date");
  } catch {
    return null;
  }
  const m = /^(\d{2})(\d{2})(\d{4})$/.exec(value ?? "");
  return m ? makeDate(Number(m[3]), Number(m[2]), Number(m[1])) : null;
}

/** travelpayouts.parse_response: round trips within the nights range; the rest is dropped. */
function parseResponse(payload: any, minNights: number, maxNights: number): Offer[] {
  if (!payload?.success) throw new CheckError(`API error: ${payload?.error || "unknown"}`);
  const offers: Offer[] = [];
  for (const item of payload.data ?? []) {
    const price = item.price;
    const departureAt = item.departure_at;
    const returnAt = item.return_at;
    if (!departureAt || !returnAt || typeof price !== "number" || !Number.isFinite(price) || price <= 0) continue;
    const link: string | null = item.link ?? null;
    // datetime.fromisoformat(x).date(): the date as written, in the timestamp's own offset.
    const [departure, ret] = localDates(link, String(departureAt).slice(0, 10), String(returnAt).slice(0, 10));
    const nights = nightsBetween(departure, ret);
    if (nights < minNights || nights > maxNights) continue;
    offers.push({
      departure, return: ret, price,
      transfers: typeof item.transfers === "number" ? item.transfers : null,
      return_transfers: typeof item.return_transfers === "number" ? item.return_transfers : null,
      found_date: foundDate(link),
    });
  }
  return offers;
}

/** models.RouteRules.allows for a provider offer. */
function allows(rules: Rules, o: Offer): boolean {
  const nights = nightsBetween(o.departure, o.return);
  if (nights < rules.min_nights || nights > rules.max_nights) return false;
  const limit = rules.direct_only ? 0 : rules.max_transfers;
  if (limit === null) return true;
  return o.transfers !== null && o.return_transfers !== null && o.transfers <= limit && o.return_transfers <= limit;
}

/** RouteRules.allows for the deal itself, from what the snapshot knows (`direct`). */
function dealAllowed(rules: Rules, deal: CheckTarget): boolean {
  const nights = nightsBetween(deal.departure_date, deal.return_date);
  if (nights < rules.min_nights || nights > rules.max_nights) return false;
  const limit = rules.direct_only ? 0 : rules.max_transfers;
  if (limit === null) return true;
  if (deal.direct === null) return false;       // unknown counts never pass a limit
  return deal.direct || limit >= 1;             // not direct: at least one stop somewhere
}

/** recheck._rule_broken */
function ruleBroken(rules: Rules, deal: CheckTarget): string {
  const nights = nightsBetween(deal.departure_date, deal.return_date);
  if (nights < rules.min_nights || nights > rules.max_nights) {
    return `fora do intervalo de ${rules.min_nights}–${rules.max_nights} noites da rota`;
  }
  if (rules.direct_only) return "não é ida e volta com voos diretos (regra direct_only)";
  return `tem mais de ${rules.max_transfers} escala(s) num dos sentidos (regra max_transfers)`;
}

/** recheck.recheck on a prices_for_dates payload (pure). `now` is the fetch time. */
export function recheckPayload(deal: CheckTarget, payload: unknown, now: Date): Recheck {
  const rules = deal.live_check.rules;
  const latest = parseResponse(payload, rules.min_nights, rules.max_nights);
  if (!dealAllowed(rules, deal)) return { valid: false, price_eur: null, reason: ruleBroken(rules, deal) };
  const sameTrip = latest.filter((o) => allows(rules, o)
    && o.departure === deal.departure_date && o.return === deal.return_date);
  if (!sameTrip.length) {
    return { valid: false, price_eur: null, reason: "a viagem já não aparece nos preços mais recentes" };
  }
  // min(): the first of the cheapest, like Python's.
  const best = sameTrip.reduce((a, b) => (b.price < a.price ? b : a));
  if (best.price > deal.price_eur) {
    return { valid: false, price_eur: best.price, reason: `o preço subiu para ${eurPlain(best.price)}` };
  }
  // detector.is_fresh: the day it was found (else the day we fetched it) within the window.
  const today = iso(now.getTime());
  const since = iso(dayMs(today) - rules.max_offer_age_days * DAY_MS);
  const seen = best.found_date ?? today;
  if (seen < since) {
    return { valid: false, price_eur: best.price,
      reason: `o preço foi visto pela última vez a ${numericDayMonth(seen)}, há mais de ${rules.max_offer_age_days} dias` };
  }
  return { valid: true, price_eur: best.price, reason: `continua a ${eurPlain(best.price)}` };
}

/** UTC to the second with a Z (db.utc_iso), what the contracts carry. */
export function utcIso(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** pipeline.price_now: the deal's route-month priced now, judged by the recheck rule.
 * Throws CheckError ("Não foi possível verificar o preço agora: ...") when the provider fails. */
export async function liveCheck(deal: CheckTarget, deps: { token: string; fetch: typeof fetch; now: () => Date }): Promise<LiveCheck> {
  const params = new URLSearchParams(Object.entries(deal.live_check.query).map(([k, v]) => [k, String(v)]));
  let payload: unknown;
  try {
    const res = await deps.fetch(`${API_URL}?${params}`, {
      headers: { "X-Access-Token": deps.token, Accept: "application/json" },
    });
    if (res.status !== 200) throw new CheckError(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
    payload = await res.json();
  } catch (exc) {
    throw new CheckError(`Não foi possível verificar o preço agora: ${(exc as Error).message}`);
  }
  const now = deps.now();
  let result: Recheck;
  try {
    result = recheckPayload(deal, payload, now);
  } catch (exc) {
    throw new CheckError(`Não foi possível verificar o preço agora: ${(exc as Error).message}`);
  }
  return { ...result, checked_at: utcIso(now) };
}

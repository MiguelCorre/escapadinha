// The explorer's rules (D31), shared by the server-rendered pages (/explorar/, /pontes/...) and
// the client island, so a list looks and filters the same with and without JavaScript. Pure and
// browser-safe: no Node modules, no fetch. Input rows are low-prices/<ORIGIN>.json rows as the
// contract gives them; every result keeps its row, so its price stays traced to `obs` (D2).
import type { LowPriceRow, Ponte } from "./contract";
import { CTA_REL, CTA_TEXT } from "./cta";
import { count, discountParts, eur, eurParts, monthName, numericDate, shortDate } from "./format";

export interface Filters {
  maxPrice: number | null;     // euros, inclusive
  month: string | null;        // departure month, YYYY-MM
  minNights: number | null;
  maxNights: number | null;
  directOnly: boolean;         // no stop in either direction (unknown stops are not direct)
  weekendOnly: boolean;
  ponte: string | null;        // a ponte's slug (pontes.json)
}

export const NO_FILTERS: Filters = {
  maxPrice: null, month: null, minNights: null, maxNights: null, directOnly: false,
  weekendOnly: false, ponte: null,
};

export type PonteWindow = Pick<Ponte, "holiday" | "window">;

/** One destination: its cheapest matching row and how many other matching dates it has. */
export interface ExploreResult {
  row: LowPriceRow;
  more: number;
}

const DAY_MS = 86_400_000;

function day(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Monday = 0 ... Sunday = 6 (as format.ts and Python). */
function weekday(iso: string): number {
  return (new Date(day(iso)).getUTCDay() + 6) % 7;
}

export function tripNights(dep: string, ret: string): number {
  return Math.round((day(ret) - day(dep)) / DAY_MS);
}

/** Weekend rule: out on Friday or Saturday, back on the Sunday or Monday after. */
export function isWeekendTrip(dep: string, ret: string): boolean {
  const out = weekday(dep);
  const back = weekday(ret);
  const n = tripNights(dep, ret);
  return (out === 4 || out === 5) && (back === 6 || back === 0) && n >= 1 && n <= 3;
}

/** Inside the ponte's travel window and over the holiday itself (pontes.schema.json). */
export function fitsPonte(dep: string, ret: string, p: PonteWindow): boolean {
  const { start, end } = p.window;
  const holiday = p.holiday.date;
  return start <= dep && dep <= holiday && holiday <= ret && ret <= end && dep < ret;
}

function matches(r: LowPriceRow, f: Filters, ponte: PonteWindow | null | undefined): boolean {
  const [, , price, dep, ret, , , , stops] = r;
  const n = tripNights(dep, ret);
  if (f.maxPrice != null && price > f.maxPrice) return false;
  if (f.month && !dep.startsWith(`${f.month}-`)) return false;
  if (f.minNights != null && n < f.minNights) return false;
  if (f.maxNights != null && n > f.maxNights) return false;
  if (f.directOnly && stops !== 0) return false;
  if (f.weekendOnly && !isWeekendTrip(dep, ret)) return false;
  if (f.ponte && !(ponte && fitsPonte(dep, ret, ponte))) return false;
  return true;
}

/** Destinations whose low prices pass the filters, each at its cheapest, sorted by price. */
export function explore(rows: LowPriceRow[], f: Filters,
  pontes: (PonteWindow & { slug: string })[]): ExploreResult[] {
  const ponte = f.ponte ? pontes.find((p) => p.slug === f.ponte) ?? null : null;
  const byDest = new Map<string, ExploreResult>();
  for (const r of rows) {
    if (!matches(r, f, ponte)) continue;
    const seen = byDest.get(r[1]);
    if (!seen) byDest.set(r[1], { row: r, more: 0 });
    else if (cheaper(r, seen.row)) byDest.set(r[1], { row: r, more: seen.more + 1 });
    else seen.more += 1;
  }
  return [...byDest.values()].sort((a, b) => (cheaper(a.row, b.row) ? -1 : 1));
}

function cheaper(a: LowPriceRow, b: LowPriceRow): boolean {
  if (a[2] !== b[2]) return a[2] < b[2];
  if (a[3] !== b[3]) return a[3] < b[3];
  return a[0] < b[0];
}

// --- HTML of the results -------------------------------------------------------------------

/** What a result needs besides its row: names of the origin's destinations and airports. */
export interface Places {
  origin: string;
  cities: Record<string, string>;
  airports: Record<string, { name: string; remote: boolean }>;
  /** Destination code -> its route page, the contract's `path` (D30); no link without one. */
  paths?: Record<string, string>;
}

const ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(value: string | number): string {
  return String(value).replace(/[&<>"']/g, (c) => ESC[c]);
}

function stopsText(stops: number | null): string | null {
  if (stops == null) return null;
  return stops === 0 ? "direto" : count(stops, "escala", "escalas");
}

function item({ row, more }: ExploreResult, places: Places): string {
  const [obs, dest, price, dep, ret, found, , , stops, airport, typical, link] = row;
  const city = places.cities[dest] ?? dest;
  const known = airport ? places.airports[airport] : undefined;
  const remote = known?.remote ?? false;
  const headline = remote ? `${city} (${known!.name})` : city;
  const arrival = airport ? (known ? `${known.name} (${airport})` : airport) : null;
  const n = tripNights(dep, ret);
  const meta = [count(n, "noite", "noites"), stopsText(stops)].filter(Boolean).join(" · ");
  const { amount, currency } = eurParts(price);
  const below = typical > price ? discountParts(1 - price / typical).text : null;
  const route = `${places.origin}-${dest}`;
  const path = places.paths?.[dest];
  return [
    `<li data-route="${esc(route)}" class="flex flex-col gap-xs border-t-[3px] border-double border-ink bg-surface p-md">`,
    `<h3 class="font-display text-title">${path ? `<a class="text-ink no-underline hover:underline" href="${esc(path)}">${esc(headline)}</a>` : esc(headline)}</h3>`,
    `<div class="flex flex-wrap items-end gap-x-md gap-y-xs">`,
    `<p data-obs="${esc(obs)}" class="font-display num text-price text-ink">${esc(amount)}<span class="price-sign"> ${currency}</span></p>`,
    below ? `<p class="pb-2xs"><span class="tag tag-success num">${esc(below)}</span></p>` : "",
    `</div>`,
    `<p class="text-small text-muted">ida e volta, por pessoa</p>`,
    `<p class="font-semibold num">${esc(shortDate(dep))} → ${esc(shortDate(ret))} <span class="font-normal text-muted">· ${esc(meta)}</span></p>`,
    arrival ? `<p class="text-small text-muted">Chegada: ${esc(arrival)}${remote ? ' <span class="tag tag-warning">longe do centro</span>' : ""}</p>` : "",
    found ? `<p class="text-small text-muted">Encontrado por um viajante a <span class="num font-semibold text-ink">${esc(numericDate(found))}</span></p>` : "",
    `<p data-route="${esc(route)}" class="text-small text-muted">Habitual em ${esc(monthName(dep))}: <span class="num">${esc(eur(typical))}</span></p>`,
    more ? `<p class="text-small text-muted">Mais ${esc(count(more, "data", "datas"))} com preço baixo</p>` : "",
    link ? `<a class="btn mt-xs self-start" href="${esc(link)}" rel="${CTA_REL}" target="_blank">${CTA_TEXT} →</a>` : "",
    `</li>`,
  ].join("");
}

/** The line above the list: "Partida: Lisboa · 2 destinos, do mais barato para o mais caro." */
export function statusText(n: number, originName: string): string {
  if (n === 0) {
    return `Partida: ${originName} · nenhum destino com estes filtros. Experimenta outro orçamento, mês ou datas.`;
  }
  return `Partida: ${originName} · ${count(n, "destino", "destinos")}, do mais barato para o mais caro.`;
}

/** The <li> items of a result list (the page wraps them in its <ul>). */
export function resultsHtml(results: ExploreResult[], places: Places): string {
  return results.map((r) => item(r, places)).join("");
}

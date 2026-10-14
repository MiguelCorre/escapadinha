// The explorer's rules (D31), shared by the server-rendered pages (/explorar/, /pontes/...) and
// the client island, so a list looks and filters the same with and without JavaScript. Pure and
// browser-safe: no Node modules, no fetch. Input rows are low-prices/<ORIGIN>.json rows as the
// contract gives them; every result keeps its row, so its price stays traced to `obs` (D2).
import type { LowPriceRow, Ponte } from "./contract";
import { daysBetween, weekday } from "./dates";
import { count } from "./format";
import { lowPricesHtml, type LowPriceItem, type Places } from "./low-prices";

export type { Places } from "./low-prices";

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
export type ExploreResult = LowPriceItem;

/** Weekend rule (D31): out on Friday or Saturday, back on the Sunday or Monday of the same
 * weekend, so 1 to 3 nights (Saturday-Sunday to Friday-Monday); the cap keeps out a Friday
 * departure that comes back on a Sunday a week later. The explorer's checkbox says so. */
export function isWeekendTrip(dep: string, ret: string): boolean {
  const out = weekday(dep);
  const back = weekday(ret);
  const n = daysBetween(dep, ret);
  return (out === 4 || out === 5) && (back === 6 || back === 0) && n >= 1 && n <= 3;
}

/** The ponte rule (D31, pontes.schema.json): departure and return both inside the travel
 * window, from the evening before the first day off to the morning after the last one. */
export function fitsPonte(dep: string, ret: string, p: PonteWindow): boolean {
  const { start, end } = p.window;
  return start <= dep && dep < ret && ret <= end;
}

function matches(r: LowPriceRow, f: Filters, ponte: PonteWindow | null | undefined): boolean {
  const [, , price, dep, ret, , , , stops] = r;
  const n = daysBetween(dep, ret);
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

/** The line above the list: "Partida: Lisboa · 2 destinos, do mais barato para o mais caro." */
export function statusText(n: number, originName: string): string {
  if (n === 0) {
    return `Partida: ${originName} · nenhum destino com estes filtros. Experimenta outro orçamento, mês ou datas.`;
  }
  return `Partida: ${originName} · ${count(n, "destino", "destinos")}, do mais barato para o mais caro.`;
}

/** The <li> items of a result list (the page wraps them in its <ul>): the shared low-price row
 * (low-prices.ts) with each destination as its headline. */
export function resultsHtml(results: ExploreResult[], places: Places): string {
  return lowPricesHtml(results, places, { headline: true });
}

// What route pages, origin pages and destination hubs show (#14, D30), derived from the contract:
// the typical low per departure month (or that there is not enough data yet), the best months,
// the calendar of the cheapest found prices, the route's low prices and an origin's routes by kind.
// Every price keeps the id it traces to (obs, or the route key for typical lows), so the
// templates can put data-obs / data-route on the element that shows it (D2).
import type { CalendarDay, Kind, LowPriceRow, Route, SiteData } from "./contract";
import { count, discountPercent, eur, lisbonTimestamp, monthName, MONTHS, nights, numericDate, shortDate } from "./format";

/** At most this many low prices on a route page (biggest discounts, shown by departure date), as
 * on the Jinja route page (D24, `site.low_prices_per_route`); the explorer shows all of them. */
export const LOW_PRICES_PER_ROUTE = 5;
/** The destination hub's "best months" per origin. */
export const BEST_MONTHS = 3;
/** Order of the groups on an origin page. */
export const KIND_ORDER: Kind[] = ["europe", "domestic", "long_haul"];

/** "2026-11" -> "novembro de 2026". */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-");
  return `${MONTHS[Number(m) - 1]} de ${y}`;
}

export interface MonthRow {
  month: string;
  label: string;
  typicalLow: string | null;   // null: fewer days than min_baseline_days, say so instead
  average: string | null;
  days: string;                // "6 dias", or "2 de 4 dias" while there are not enough
}

/** The typical low per departure month, ascending; `minDays` = meta.detector.min_baseline_days. */
export function monthRows(route: Route, minDays: number): MonthRow[] {
  return route.months.map((m) => ({
    month: m.month,
    label: monthLabel(m.month),
    typicalLow: m.typical_low != null ? eur(m.typical_low) : null,
    average: m.average != null ? eur(m.average) : null,
    days: m.typical_low != null ? count(m.days, "dia", "dias") : `${m.days} de ${count(minDays, "dia", "dias")}`,
  }));
}

export interface BestMonth {
  month: string;
  label: string;
  typicalLow: string;
}

/** The months with the lowest typical low, cheapest first (ties: the earlier month). */
export function bestMonths(route: Route, limit = BEST_MONTHS): BestMonth[] {
  return route.months
    .filter((m) => m.typical_low != null)
    .sort((a, b) => a.typical_low! - b.typical_low! || a.month.localeCompare(b.month))
    .slice(0, limit)
    .map((m) => ({ month: m.month, label: monthLabel(m.month), typicalLow: eur(m.typical_low!) }));
}

export interface CalendarCell {
  day: number;
  date: string;
  price: {
    obs: number;
    text: string;           // "51 €"
    title: string;          // "Partida qua, 18 nov, regresso qua, 25 nov"
    cheapest: boolean;      // the month's lowest
  } | null;
}

export interface CalendarMonth {
  month: string;
  label: string;
  /** Monday-first weeks; null pads the first and last week. */
  weeks: (CalendarCell | null)[][];
}

function daysIn(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** Monday = 0, like format.ts. */
function weekday(year: number, month: number, day: number): number {
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
}

/** The route's calendar (cheapest fresh offer per departure day) as month grids. */
export function calendarMonths(route: Route): CalendarMonth[] {
  const byMonth = new Map<string, CalendarDay[]>();
  for (const day of route.calendar) {
    const month = day.dep.slice(0, 7);
    if (!byMonth.has(month)) byMonth.set(month, []);
    byMonth.get(month)!.push(day);
  }
  return [...byMonth.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([month, days]) => {
    const [y, m] = month.split("-").map(Number);
    const low = Math.min(...days.map((d) => d.price));
    const byDate = new Map(days.map((d) => [d.dep, d]));
    const cells: (CalendarCell | null)[] = Array(weekday(y, m, 1)).fill(null);
    for (let day = 1; day <= daysIn(y, m); day++) {
      const date = `${month}-${String(day).padStart(2, "0")}`;
      const found = byDate.get(date);
      cells.push({
        day, date,
        price: found ? {
          obs: found.obs, text: eur(found.price), cheapest: found.price === low,
          title: `Partida ${shortDate(found.dep)}, regresso ${shortDate(found.ret)}`,
        } : null,
      });
    }
    while (cells.length % 7) cells.push(null);
    const weeks = [];
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
    return { month, label: monthLabel(month), weeks };
  });
}

export interface LowPriceView {
  obs: number;
  route: string;
  price: string;
  discount: string;           // "−32%"
  typicalLow: string;         // the departure month's typical low (data-route)
  month: string;              // "novembro"
  dates: string;              // "sáb, 14 nov → ter, 17 nov"
  nights: string;
  airline: string | null;
  stops: string | null;       // "voos diretos", "1 escala"; null when unknown
  airport: string | null;     // "Beauvais (BVA)"
  remote: boolean;
  foundOn: string | null;     // the traveller's found date
  fetchedAt: string;          // ours, Lisbon time
  link: string | null;
}

function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

function stopsText(n: number | null): string | null {
  if (n == null) return null;
  return n === 0 ? "voos diretos" : count(n, "escala", "escalas");
}

/** The route's low prices from its origin's file: the biggest discounts (at most `limit`), shown
 * by departure date; a live promotion's own offer (`promoted` obs ids) is shown above them. */
export function routeLowPrices(data: SiteData, route: Route, promoted: Set<number>,
  limit = LOW_PRICES_PER_ROUTE): LowPriceView[] {
  const rows = (data.lowPrices[route.origin]?.rows ?? [])
    .filter((r) => r[1] === route.destination && !promoted.has(r[0]));
  const off = (r: LowPriceRow) => (r[10] - r[2]) / r[10];
  return rows
    .sort((a, b) => off(b) - off(a) || a[2] - b[2] || a[0] - b[0])
    .slice(0, limit)
    .sort((a, b) => a[3].localeCompare(b[3]) || a[4].localeCompare(b[4]) || a[0] - b[0])
    .map((r) => {
      const [obs, , price, dep, ret, found, fetched, airline, stops, airport, typical, link] = r;
      const known = airport ? data.labels.airports[airport] : undefined;
      return {
        obs, route: route.key, price: eur(price),
        discount: discountPercent(Math.round(off(r) * 100)),
        typicalLow: eur(typical), month: monthName(dep),
        dates: `${shortDate(dep)} → ${shortDate(ret)}`, nights: nights(daysBetween(dep, ret)),
        airline: airline ? data.labels.airlines[airline] ?? airline : null,
        stops: stopsText(stops),
        airport: airport ? (known ? `${known.name} (${airport})` : airport) : null,
        remote: known?.remote ?? false,
        foundOn: found ? numericDate(found) : null,
        fetchedAt: lisbonTimestamp(fetched),
        link,
      };
    });
}

export interface OriginGroup {
  kind: Kind;
  label: string;        // labels.json kinds: "Europa", "Portugal", "Longo curso"
  routes: Route[];
}

/** An origin's routes by kind (KIND_ORDER), each by the Portuguese city name. */
export function originGroups(data: SiteData, origin: string): OriginGroup[] {
  const mine = data.routes.routes.filter((r) => r.origin === origin);
  return KIND_ORDER.map((kind) => ({
    kind, label: data.labels.kinds[kind],
    routes: mine.filter((r) => r.kind === kind).sort((a, b) => a.city.localeCompare(b.city, "pt")),
  })).filter((g) => g.routes.length > 0);
}

/** "voos diretos, estadias de 2 a 10 noites": which offers the route's numbers count. */
export function rulesText(route: Route): string {
  const { direct_only, min_nights, max_nights, max_transfers } = route.rules;
  const stops = direct_only || max_transfers === 0 ? "voos diretos"
    : max_transfers == null ? "com ou sem escalas"
    : `até ${count(max_transfers, "escala", "escalas")} em cada sentido`;
  return `${stops}, estadias de ${min_nights} a ${max_nights} noites`;
}

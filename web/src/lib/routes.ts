// What route pages, origin pages and destination hubs show (#14, D30), derived from the contract:
// the typical low per departure month (or that there is not enough data yet), the best months,
// the calendar of the cheapest found prices, the route's low prices and an origin's routes by kind.
// Every price keeps the id it traces to (obs, or the route key for typical lows), so the
// templates can put data-obs / data-route on the element that shows it (D2).
import type { CalendarDay, Detector, Kind, LowPriceRow, Route, SiteData } from "./contract";
import { daysInMonth, weekday } from "./dates";
import { placesFor } from "./explorer-data";
import { count, eur, integer, monthList, monthYear, shortDate } from "./format";
import { lowPriceView, type LowPriceView } from "./low-prices";

/** At most this many low prices on a route page (biggest discounts, shown by departure date,
 * D24); the explorer shows all of them. */
export const LOW_PRICES_PER_ROUTE = 5;
/** The destination hub's "best months" per origin. */
export const BEST_MONTHS = 3;
/** Order of the groups on an origin page. */
export const KIND_ORDER: Kind[] = ["europe", "domestic", "long_haul"];

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
    label: monthYear(m.month),
    typicalLow: m.typical_low != null ? eur(m.typical_low) : null,
    average: m.average != null ? eur(m.average) : null,
    days: m.typical_low != null ? count(m.days, "dia", "dias") : `${m.days} de ${count(minDays, "dia", "dias")}`,
  }));
}

/** What "ainda sem dados suficientes" means, from `meta.detector` (D27, D40): the daily lows a
 * month needs and, when more than one, the departure dates a day must have seen to count. */
export function typicalLowRule(det: Pick<Detector, "min_baseline_days" | "min_dates_per_day">): string {
  const dates = det.min_dates_per_day ?? 1;
  const which = dates > 1 ? `, contando só os dias com preços para ${dates} ou mais datas de partida,` : "";
  return `Precisamos de pelo menos ${det.min_baseline_days} dias de dados num mês${which} antes de dizer o que é habitual.`;
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
    .map((m) => ({ month: m.month, label: monthYear(m.month), typicalLow: eur(m.typical_low!) }));
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
    const cells: (CalendarCell | null)[] = Array(weekday(`${month}-01`)).fill(null);
    for (let day = 1; day <= daysInMonth(y, m); day++) {
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
    return { month, label: monthYear(month), weeks };
  });
}

/** The route's low prices from its origin's file: the biggest discounts (at most `limit`), shown
 * by departure date; a live promotion's own offer (`promoted` obs ids) is shown above them. */
export function routeLowPrices(data: SiteData, route: Route, promoted: Set<number>,
  limit = LOW_PRICES_PER_ROUTE): LowPriceView[] {
  const rows = (data.lowPrices[route.origin]?.rows ?? [])
    .filter((r) => r[1] === route.destination && !promoted.has(r[0]));
  const off = (r: LowPriceRow) => (r[10] - r[2]) / r[10];
  const picked = rows
    .sort((a, b) => off(b) - off(a) || a[2] - b[2] || a[0] - b[0])
    .slice(0, limit);
  const places = placesFor(data, route.origin, picked);
  return picked
    .sort((a, b) => a[3].localeCompare(b[3]) || a[4].localeCompare(b[4]) || a[0] - b[0])
    .map((row) => lowPriceView({ row, more: 0 }, places));
}

export interface OriginGroup {
  kind: Kind;
  label: string;        // labels.json kinds: "Europa", "Portugal", "Longo curso"
  routes: Route[];
}

/** The order of an origin page's routes and a destination hub's origins (D45): the cheapest
 * found price first, then the busiest route (Eurostat passengers per month), then whatever
 * order the caller had (the city name, the contract's origin order). Routes without a recent
 * price come after those with one, the busiest first; dormant routes have none. */
export function byPriceThenDemand(a: Pick<Route, "cheapest" | "demand">,
  b: Pick<Route, "cheapest" | "demand">): number {
  const priceA = a.cheapest?.price ?? Infinity;
  const priceB = b.cheapest?.price ?? Infinity;
  if (priceA !== priceB) return priceA < priceB ? -1 : 1;
  return (b.demand?.pax_month ?? -1) - (a.demand?.pax_month ?? -1);
}

/** An origin's routes by kind (KIND_ORDER), each by price, then demand, then city name. */
export function originGroups(data: SiteData, origin: string): OriginGroup[] {
  const mine = data.routes.routes.filter((r) => r.origin === origin);
  return KIND_ORDER.map((kind) => ({
    kind, label: data.labels.kinds[kind],
    routes: mine.filter((r) => r.kind === kind)
      .sort((a, b) => byPriceThenDemand(a, b) || a.city.localeCompare(b.city, "pt")),
  })).filter((g) => g.routes.length > 0);
}

export interface DemandView {
  /** "141 591" passengers per month (a count, never a price). */
  paxMonth: string;
  /** "dezembro de 2024": the last month the dataset has. */
  period: string;
  /** Below meta.demand.thin_pax_month: with no recent price, the page says the route has little
   * demand and prices show up rarely. */
  thin: boolean;
  /** Months the dataset shows without passengers, as "janeiro, fevereiro e março de 2024";
   * null when every month had some: a seasonal route (or one that ended). */
  zeroMonths: string | null;
}

/** What a route page says about demand (D45), or null without Eurostat data: then nothing. */
export function demandView(route: Pick<Route, "demand">, rules: { thin_pax_month: number }): DemandView | null {
  const d = route.demand;
  if (!d) return null;
  const zero = d.months.filter((m) => m.pax === 0).map((m) => m.month);
  return {
    paxMonth: integer(d.pax_month),
    period: monthYear(d.period),
    thin: d.pax_month < rules.thin_pax_month,
    zeroMonths: zero.length ? zeroMonthsText(zero) : null,
  };
}

/** ["2024-01", "2024-02", "2024-11"] -> "janeiro, fevereiro e novembro de 2024"; months of
 * several years are listed per year ("novembro e dezembro de 2023 e janeiro de 2024"). */
function zeroMonthsText(months: string[]): string {
  const byYear = new Map<string, number[]>();
  for (const m of months) {
    const [year, month] = m.split("-");
    if (!byYear.has(year)) byYear.set(year, []);
    byYear.get(year)!.push(Number(month));
  }
  const parts = [...byYear.entries()].sort(([a], [b]) => a.localeCompare(b))
    .map(([year, list]) => `${monthList(list)} de ${year}`);
  return parts.length > 1 ? `${parts.slice(0, -1).join(", ")} e ${parts.at(-1)}` : parts[0];
}

/** "voos diretos, estadias de 2 a 10 noites": which offers the route's numbers count. */
export function rulesText(route: Route): string {
  const { direct_only, min_nights, max_nights, max_transfers } = route.rules;
  const stops = direct_only || max_transfers === 0 ? "voos diretos"
    : max_transfers == null ? "com ou sem escalas"
    : `até ${count(max_transfers, "escala", "escalas")} em cada sentido`;
  return `${stops}, estadias de ${min_nights} a ${max_nights} noites`;
}

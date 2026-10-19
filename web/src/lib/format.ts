// pt-PT formatting for the site, mirroring src/escapadinha/i18n_pt.py (no OS locale, no Intl
// month names: the words are ours). Dates in the contract are ISO strings; instants are UTC and
// shown in Europe/Lisbon time. The month and weekday words equal labels.json (a test checks it).
// Every pt-PT word for a date, a price or a trip comes from here: pages and components never
// spell out month or weekday names themselves. Day arithmetic is dates.ts's.
import { weekday } from "./dates";

export const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
  "agosto", "setembro", "outubro", "novembro", "dezembro"];
export const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out",
  "nov", "dez"];
/** Monday first, like Python's date.weekday(). */
export const WEEKDAYS_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
/** Monday first: the full names ("segunda-feira"), e.g. for a calendar column's `abbr`. */
export const WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira",
  "sábado", "domingo"];

const NBSP = " ";
const MINUS = "−";

/** A price in parts, so a component can style the sign without parsing the text. */
export interface EurParts {
  amount: string;     // "49,50"
  currency: string;   // "€"
  text: string;       // "49,50 €" (no-break space)
}

/** 49.5 -> {amount: "49,50", currency: "€", text: "49,50 €"}. */
export function eurParts(amount: number): EurParts {
  const digits = Number.isInteger(amount) ? String(amount) : amount.toFixed(2).replace(".", ",");
  return { amount: digits, currency: "€", text: `${digits}${NBSP}€` };
}

/** 49 -> "49 €", 49.5 -> "49,50 €", 1299 -> "1299 €" (no-break space before the sign). */
export function eur(amount: number): string {
  return eurParts(amount).text;
}

/** i18n_pt.eur with a plain space ("58 €"), as the pipeline writes the recheck's reasons. */
export function eurPlain(amount: number): string {
  const { amount: digits, currency } = eurParts(amount);
  return `${digits} ${currency}`;
}

/** A discount in parts: the true minus sign and the percentage. */
export interface DiscountParts {
  sign: string;       // "−"
  value: string;      // "44%"
  text: string;       // "−44%"
}

/** A whole percentage below the usual price: 44 -> {sign: "−", value: "44%", text: "−44%"}. */
function percentParts(pct: number): DiscountParts {
  const value = `${pct}%`;
  return { sign: MINUS, value, text: `${MINUS}${value}` };
}

/** 0.4397 -> parts of "−44%" (rounded like the slides). */
export function discountParts(fraction: number): DiscountParts {
  return percentParts(Math.round(fraction * 100));
}

/** 0.4397 -> "−44%" (true minus sign, rounded like the slides). */
export function discount(fraction: number): string {
  return discountParts(fraction).text;
}

/** A whole percentage below the usual price: 44 -> "−44%". */
export function discountPercent(pct: number): string {
  return percentParts(pct).text;
}

function parts(iso: string): { y: number; m: number; d: number; weekday: number } {
  const [y, m, d] = iso.split("-").map(Number);
  return { y, m, d, weekday: weekday(iso) };
}

/** "2026-11-06" -> "sex, 6 nov". */
export function shortDate(iso: string): string {
  const { m, d, weekday } = parts(iso);
  return `${WEEKDAYS_SHORT[weekday]}, ${d} ${MONTHS_SHORT[m - 1]}`;
}

/** "2026-10-07" -> "07/10/2026". */
export function numericDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}

/** "2026-10-05" -> "05/10" (Python's `%d/%m`, as the recheck's reasons print it). */
export function numericDayMonth(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

/** "2026-11-06" -> "6 de novembro". */
export function dayMonth(iso: string): string {
  const { m, d } = parts(iso);
  return `${d} de ${MONTHS[m - 1]}`;
}

/** "2026-10-14" -> "14 de outubro de 2026" (e.g. when an article's facts were checked). */
export function dayMonthYear(iso: string): string {
  return `${dayMonth(iso)} de ${parts(iso).y}`;
}

/** [4, 5, 9] -> "abril, maio e setembro" (months 1-12, in the given order). */
export function monthList(months: readonly number[]): string {
  const words = months.map((m) => MONTHS[m - 1]);
  return words.length < 2 ? words.join("") : `${words.slice(0, -1).join(", ")} e ${words.at(-1)}`;
}

/** "6 a 9 de novembro","27 de novembro a 4 de dezembro"; with years when it crosses one. */
export function dateRange(start: string, end: string): string {
  const a = parts(start);
  const b = parts(end);
  if (a.y !== b.y) return `${dayMonth(start)} de ${a.y} a ${dayMonth(end)} de ${b.y}`;
  if (a.m === b.m) return `${a.d} a ${dayMonth(end)}`;
  return `${dayMonth(start)} a ${dayMonth(end)}`;
}

/** "2026-11-30" -> "segunda-feira, 30 de novembro". */
export function longDate(iso: string): string {
  return `${WEEKDAYS[parts(iso).weekday]}, ${dayMonth(iso)}`;
}

/** "2026-12-01" -> "terça-feira, 1 de dezembro de 2026". */
export function longDateYear(iso: string): string {
  return `${longDate(iso)} de ${parts(iso).y}`;
}

/** "2026-10" -> "outubro de 2026". */
export function monthYear(month: string): string {
  const [y, m] = month.split("-");
  return `${MONTHS[Number(m) - 1]} de ${y}`;
}

/** "2026-12" or "2026-12-09" -> "dezembro". */
export function monthName(iso: string): string {
  return MONTHS[Number(iso.split("-")[1]) - 1];
}

const LISBON = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Lisbon",
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

/** UTC instant -> "12/10/2026 às 22:17" in Lisbon time. */
export function lisbonTimestamp(utc: string): string {
  const p = Object.fromEntries(LISBON.formatToParts(new Date(utc)).map((x) => [x.type, x.value]));
  return `${p.day}/${p.month}/${p.year} às ${p.hour}:${p.minute}`;
}

/** ("Porto", "o") -> "desde o Porto", ("Lisboa", null) -> "desde Lisboa" (origins.json article). */
export function fromPlace(name: string, article?: string | null): string {
  return article ? `desde ${article} ${name}` : `desde ${name}`;
}

/** A ponte page's title: "Ponte de 1 de dezembro desde o Porto". */
export function ponteTitle(ponteName: string, origin: { name: string; article?: string | null }): string {
  return `${ponteName} ${fromPlace(origin.name, origin.article)}`;
}

/** 141591 -> "141 591": pt-PT groups thousands with a space (no-break). For counts such as
 * passengers (D45), never for prices: a price is `eur`, with its sign. */
export function integer(n: number): string {
  const digits = String(Math.round(Math.abs(n)));
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
  return n < 0 ? `${MINUS}${grouped}` : grouped;
}

/** (1, "noite", "noites") -> "1 noite"; 0 and 2+ take the plural. */
export function count(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

export function nights(n: number): string {
  return count(n, "noite", "noites");
}

/** The baggage line (D43): true -> "com mala de porão incluída", false -> "só bagagem de mão";
 * unknown (null or absent) -> null, so the page prints no line rather than guessing. Same words
 * as the pipeline's i18n_pt.BAGGAGE (captions and slides). */
export function baggageText(baggage: boolean | null | undefined): string | null {
  if (baggage == null) return null;
  return baggage ? "com mala de porão incluída" : "só bagagem de mão";
}

/** A trip's stops (the most in either direction): 0 -> "voos diretos", 1 -> "1 escala"; unknown
 * (null) -> null, so the page says nothing rather than guessing. */
export function stopsText(stops: number | null): string | null {
  if (stops == null) return null;
  return stops === 0 ? "voos diretos" : count(stops, "escala", "escalas");
}

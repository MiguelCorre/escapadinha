// pt-PT formatting for the site, mirroring src/escapadinha/i18n_pt.py (no OS locale, no Intl
// month names: the words are ours). Dates in the contract are ISO strings; instants are UTC and
// shown in Europe/Lisbon time. The month and weekday words equal labels.json (a test checks it).

export const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
  "agosto", "setembro", "outubro", "novembro", "dezembro"];
export const MONTHS_SHORT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out",
  "nov", "dez"];
/** Monday first, like Python's date.weekday(). */
export const WEEKDAYS_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];

const NBSP = " ";
const MINUS = "−";

/** 49 -> "49 €", 49.5 -> "49,50 €", 1299 -> "1299 €" (no-break space before the sign). */
export function eur(amount: number): string {
  const text = Number.isInteger(amount) ? String(amount) : amount.toFixed(2).replace(".", ",");
  return `${text}${NBSP}€`;
}

/** 0.4397 -> "−44%" (true minus sign, rounded like the slides). */
export function discount(fraction: number): string {
  return `${MINUS}${Math.round(fraction * 100)}%`;
}

function parts(iso: string): { y: number; m: number; d: number; weekday: number } {
  const [y, m, d] = iso.split("-").map(Number);
  const js = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = Sunday
  return { y, m, d, weekday: (js + 6) % 7 };
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

/** "2026-11-06" -> "6 de novembro". */
export function dayMonth(iso: string): string {
  const { m, d } = parts(iso);
  return `${d} de ${MONTHS[m - 1]}`;
}

/** "6 a 9 de novembro", "27 de novembro a 4 de dezembro"; with years when it crosses one. */
export function dateRange(start: string, end: string): string {
  const a = parts(start);
  const b = parts(end);
  if (a.y !== b.y) return `${dayMonth(start)} de ${a.y} a ${dayMonth(end)} de ${b.y}`;
  if (a.m === b.m) return `${a.d} a ${dayMonth(end)}`;
  return `${dayMonth(start)} a ${dayMonth(end)}`;
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

/** (1, "noite", "noites") -> "1 noite"; 0 and 2+ take the plural. */
export function count(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

export function nights(n: number): string {
  return count(n, "noite", "noites");
}

// Calendar arithmetic on the contract's ISO days ("2026-11-27"), the one set every module uses
// (format.ts, explorer.ts, routes.ts, the island): no time zone involved, days counted in UTC so
// a clock change never shifts a count. Instants (UTC "...Z") become a Lisbon calendar day with
// `lisbonDay`. Pure and browser-safe. The words for these days are format.ts's job.

const DAY_MS = 86_400_000;

/** "2026-11-27" -> its midnight in UTC, in milliseconds (for comparisons and counts). */
export function dayNumber(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Monday = 0 ... Sunday = 6, like Python's date.weekday(). */
export function weekday(iso: string): number {
  return (new Date(dayNumber(iso)).getUTCDay() + 6) % 7;
}

/** Whole days from `a` to `b` ("2026-10-31" -> "2026-11-03": 3); a trip's nights. */
export function daysBetween(a: string, b: string): number {
  return Math.round((dayNumber(b) - dayNumber(a)) / DAY_MS);
}

/** The number of days in a month (month 1-12). */
export function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

const LISBON_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Lisbon", year: "numeric", month: "2-digit", day: "2-digit",
});

/** A UTC instant's calendar day in Lisbon: "2026-07-01T23:30:00Z" -> "2026-07-02". */
export function lisbonDay(utc: string): string {
  const p = Object.fromEntries(LISBON_DAY.formatToParts(new Date(utc)).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}`;
}

// Build-time inputs of the explorer (D31): the per-origin JSON files the island loads lazily
// (/explorar/dados/<ORIGIN>.json: the contract's rows plus the names they need), and the small
// configuration the page embeds for the island. Nothing here ships to the browser.
import type { LowPriceRow, SiteData } from "./contract";
import { bookingLink } from "./cta";
import type { PonteWindow } from "./explorer";
import type { Places } from "./low-prices";

/** /explorar/dados/<ORIGIN>.json */
export interface OriginFile {
  origin: string;
  generated_at: string;
  rows: LowPriceRow[];
  places: Places;
}

export interface IslandConfig {
  defaultOrigin: string;
  origins: { iata: string; name: string; file: string }[];
  pontes: (PonteWindow & { slug: string })[];
}

export function dataFile(iata: string): string {
  return `/explorar/dados/${iata}.json`;
}

/** Names of the destinations, arrival airports and airlines that `rows` (default: all of the
 * origin's low prices) mention, and the route pages (D30) the rows link to. */
export function placesFor(data: SiteData, iata: string,
  rows: readonly LowPriceRow[] = data.lowPrices[iata]?.rows ?? []): Places {
  const cities: Record<string, string> = {};
  const airports: Places["airports"] = {};
  const airlines: Record<string, string> = {};
  const paths: Record<string, string> = {};
  for (const r of rows) {
    const route = data.routes.routes.find((x) => x.key === `${iata}-${r[1]}`);
    cities[r[1]] = route?.city ?? data.destinations.destinations.find((d) => d.code === r[1])?.city ?? r[1];
    if (route) paths[r[1]] = route.path;
    const label = r[9] ? data.labels.airports[r[9]] : undefined;
    if (r[9] && label) airports[r[9]] = label;
    const airline = r[7] ? data.labels.airlines[r[7]] : undefined;
    if (r[7] && airline) airlines[r[7]] = airline;
  }
  return { origin: iata, cities, airports, airlines, paths };
}

/** /explorar/dados/<ORIGIN>.json. Every row's link passes the booking-link rule here, at build
 * time (cta.ts: https only), so the island never meets a link the server would refuse. */
export function originFile(data: SiteData, iata: string): OriginFile {
  const file = data.lowPrices[iata];
  for (const row of file.rows) bookingLink(row[11]);
  return { origin: iata, generated_at: file.generated_at, rows: file.rows, places: placesFor(data, iata) };
}

export function islandConfig(data: SiteData): IslandConfig {
  return {
    defaultOrigin: defaultOrigin(data),
    origins: data.origins.origins.map((o) => ({ iata: o.iata, name: o.name, file: dataFile(o.iata) })),
    pontes: data.pontes.pontes.map((p) => ({ slug: p.slug, holiday: p.holiday, window: p.window })),
  };
}

/** Departure months (YYYY-MM) with low prices from any origin, ascending. */
export function months(data: SiteData): string[] {
  const all = Object.values(data.lowPrices).flatMap((f) => f.rows.map((r) => r[3].slice(0, 7)));
  return [...new Set(all)].sort();
}

/** The origin the explorer opens on: the first one with low prices (else the first). */
export function defaultOrigin(data: SiteData): string {
  const origins = data.origins.origins;
  return (origins.find((o) => (data.lowPrices[o.iata]?.rows.length ?? 0) > 0) ?? origins[0]).iata;
}

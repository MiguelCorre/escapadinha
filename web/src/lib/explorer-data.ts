// Build-time inputs of the explorer (D31): the per-origin JSON files the island loads lazily
// (/explorar/dados/<ORIGIN>.json: the contract's rows plus the names they need), and the small
// configuration the page embeds for the island. Nothing here ships to the browser.
import type { LowPriceRow, SiteData } from "./contract";
import type { Places, PonteWindow } from "./explorer";

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

/** Names of the destinations and arrival airports one origin's rows mention. */
export function placesFor(data: SiteData, iata: string): Places {
  const rows = data.lowPrices[iata]?.rows ?? [];
  const cities: Record<string, string> = {};
  const airports: Places["airports"] = {};
  for (const r of rows) {
    const route = data.routes.routes.find((x) => x.key === `${iata}-${r[1]}`);
    cities[r[1]] = route?.city ?? data.destinations.destinations.find((d) => d.code === r[1])?.city ?? r[1];
    const label = r[9] ? data.labels.airports[r[9]] : undefined;
    if (r[9] && label) airports[r[9]] = label;
  }
  return { origin: iata, cities, airports };
}

export function originFile(data: SiteData, iata: string): OriginFile {
  const file = data.lowPrices[iata];
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

// A synthetic contract dataset at full size (#14, D30): the committed fixtures have 10 routes, the
// real data ~360 routes from 6 origins to ~156 destinations. This writes a dataset of that size into
// a temporary folder so scale.test.ts can build it and measure the build. It is test data in every
// way: meta.fixture is true, cities are "Destino de teste AB", codes start with Z (destinations)
// and Y (airports), links point at example.com, and the prices are made up by a seeded generator,
// never shown anywhere but in a temporary build. It must stay valid against contract/site/v1
// (loadSiteData validates it before the build).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type {
  CalendarDay, Destination, LowPriceRow, Meta, Origin, Promotion, Route, RouteMonth,
} from "../src/lib/contract";
import { FIXTURES_DIR } from "../src/lib/site-data";

/** Routes per origin as in the real data on 2026-10-14 (360 routes, 156 destinations). */
export const SCALE = { LIS: 111, OPO: 108, FAO: 67, FNC: 49, PDL: 17, TER: 8 } as const;
export const DESTINATIONS = 156;
const NAMES: Record<string, string> = {
  LIS: "Lisboa", OPO: "Porto", FAO: "Faro", FNC: "Madeira", PDL: "Ponta Delgada", TER: "Terceira",
};
const MONTHS = ["2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04"];
const GENERATED_AT = "2026-10-14T09:00:00Z";

/** Deterministic pseudo-random numbers (a linear congruential generator). */
function random(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

/** 0 -> "A", 25 -> "Z", 26 -> "BA" (base 26 in letters). */
const letters = (i: number): string => (i >= 26 ? letters(Math.floor(i / 26)) : "") + String.fromCharCode(65 + (i % 26));
const code = (prefix: string, i: number) => `${prefix}${i.toString(36).toUpperCase().padStart(2, "0")}`;
const slug = (city: string) => city.toLowerCase().replace(/[^a-z0-9]+/g, "-");
const addDays = (iso: string, n: number) =>
  new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);

export interface Synthetic {
  routes: Route[];
  origins: Origin[];
  destinations: Destination[];
  dormant: Route[];
}

/** Write the dataset into `dir` (created) and return what it holds. */
export function writeSyntheticData(dir: string, seed = 14): Synthetic {
  const rand = random(seed);
  let obs = 100_000;
  const destCode = (i: number) => code("Z", i);
  // Letters, not numbers: a city name ending in a digit would run into the price after it.
  const city = (i: number) => `Destino de teste ${letters(i)}`;
  const routes: Route[] = [];
  const lowRows: Record<string, LowPriceRow[]> = {};
  let start = 0;
  for (const [origin, n] of Object.entries(SCALE)) {
    lowRows[origin] = [];
    for (let k = 0; k < n; k++) {
      const d = (start + k * 7) % DESTINATIONS;
      const key = `${origin}-${destCode(d)}`;
      const dormant = (start + k) % 23 === 5;
      const base = 40 + Math.round(rand() * 400);
      const months: RouteMonth[] = MONTHS.map((month, m) => {
        const days = dormant ? 0 : Math.floor(rand() * 9);       // 0..8: some below the minimum (4)
        const low = Math.round(base * (0.8 + rand() * 0.5) * 2) / 2;
        return days >= 4
          ? { month, typical_low: low, average: Math.round((low * 1.12) * 100) / 100, days }
          : { month, typical_low: null, average: null, days: m === 0 && dormant ? 0 : days };
      });
      const calendar: CalendarDay[] = [];
      if (!dormant) {
        for (let day = 0; day < 150; day += 1 + Math.floor(rand() * 5)) {
          const dep = addDays("2026-11-01", day);
          calendar.push({ dep, ret: addDays(dep, 2 + Math.floor(rand() * 8)), obs: obs++, price: Math.round(base * (0.6 + rand() * 0.9)) });
        }
      }
      const cheapestDay = calendar.reduce<CalendarDay | null>((a, c) => (!a || c.price < a.price ? c : a), null);
      for (const c of calendar) {
        const typical = months.find((m) => m.month === c.dep.slice(0, 7))?.typical_low;
        if (typical != null && c.price <= typical * 0.85 && lowRows[origin].length < 1500) {
          lowRows[origin].push([c.obs, destCode(d), c.price, c.dep, c.ret, "2026-10-13", "2026-10-13T20:15Z",
            "FR", 0, code("Y", d), typical, `https://example.com/parceiro/site-low-${c.obs}`,
            c.obs % 3 === 0 ? null : c.obs % 3 === 1]);   // baggage known for two thirds (D39)
        }
      }
      routes.push({
        key, origin, destination: destCode(d), city: city(d), city_en: null,
        kind: d % 10 === 0 ? "long_haul" : d % 13 === 0 ? "domestic" : "europe",
        status: dormant ? "dormant" : "active", airports: [code("Y", d)],
        rules: { direct_only: true, min_nights: 2, max_nights: 10, max_transfers: 0 },
        path: `/voos/${slug(NAMES[origin])}-${slug(city(d))}/`, months,
        cheapest: cheapestDay ? {
          obs: cheapestDay.obs, route: key, price: cheapestDay.price, departure: cheapestDay.dep,
          return: cheapestDay.ret, nights: Math.round((Date.parse(cheapestDay.ret) - Date.parse(cheapestDay.dep)) / 86_400_000),
          airline: "FR", transfers: 0, return_transfers: 0, arrival_airport: code("Y", d),
          found_date: "2026-10-13", fetched_at: "2026-10-13T20:15:00Z", baggage: null,
        } : null,
        calendar,
        counts: { observations: calendar.length * 3, low_prices: 0, promotions_live: 0, promotions_expired: 0 },
        discovered_at: "2026-10-13T17:14:28Z",
        last_observed_at: dormant ? "2026-09-01T10:00:00Z" : "2026-10-14T08:00:00Z",
      });
    }
    start += 31;
  }
  routes.sort((a, b) => a.key.localeCompare(b.key));
  for (const r of routes) r.counts.low_prices = lowRows[r.origin].filter((row) => row[1] === r.destination).length;
  for (const rows of Object.values(lowRows)) rows.sort((a, b) => a[3].localeCompare(b[3]) || a[0] - b[0]);

  // One live and one expired promotion on the busiest origin's first route with a price.
  const promoted = routes.find((r) => r.origin === "LIS" && r.cheapest)!;
  const offer = promoted.cheapest!;
  const promotion = (id: number, live: boolean): Promotion => ({
    id, route: promoted.key, status: live ? "approved" : "expired", live,
    path: `/promos/${id}-${promoted.path.slice("/voos/".length)}`,
    offer, typical_low: null, baseline_days: 0, discount_pct: null, rule: "price_cap",
    detected_at: "2026-10-13T20:20:00Z", approved_at: "2026-10-13T21:00:00Z", published_at: null,
    checked_at: "2026-10-14T08:00:00Z",
    booking_link: live ? `https://example.com/parceiro/site-deal-${id}` : null,
    expired: live ? null : { reason: "o voo deixou de aparecer na pesquisa", latest: null },
    images: { slides: [`/img/promos/${id}/slide_01.webp`], thumb: `/img/promos/${id}/thumb.webp`, og: `/img/promos/${id}/og.jpg` },
  });
  const promotions = [promotion(2, true), promotion(1, false)];
  promoted.counts.promotions_live = 1;
  promoted.counts.promotions_expired = 1;

  const origins: Origin[] = Object.keys(SCALE).map((iata) => {
    const mine = routes.filter((r) => r.origin === iata);
    return {
      iata, name: NAMES[iata], slug: slug(NAMES[iata]), path: `/partidas/${slug(NAMES[iata])}/`,
      routes: { active: mine.filter((r) => r.status === "active").length, dormant: mine.filter((r) => r.status === "dormant").length },
      low_prices: lowRows[iata].length, promotions_live: iata === "LIS" ? 1 : 0,
    };
  });
  const destinations: Destination[] = [];
  for (let d = 0; d < DESTINATIONS; d++) {
    const mine = routes.filter((r) => r.destination === destCode(d));
    if (!mine.length) continue;
    destinations.push({
      code: destCode(d), city: city(d), city_en: null, slug: slug(city(d)), path: `/destinos/${slug(city(d))}/`,
      kinds: [mine[0].kind], airports: [code("Y", d)], routes: mine.map((r) => r.key).sort(), photo: null,
    });
  }
  destinations.sort((a, b) => a.code.localeCompare(b.code));

  const meta: Meta = {
    version: 1, generated_at: GENERATED_AT, fixture: true, run: { id: 99, finished_at: GENERATED_AT },
    currency: "EUR", base_url: "https://pontonomada.pt",
    detector: { low_threshold: 0.15, threshold: 0.3, min_saving_eur: 15, min_baseline_days: 4, max_offer_age_days: 3, lookback_days: 90 },
    files: {
      origins: "origins.json", routes: "routes.json", destinations: "destinations.json",
      promotions: "promotions.json", labels: "labels.json",
      low_prices: Object.fromEntries(Object.keys(SCALE).map((o) => [o, `low-prices/${o}.json`])),
    },
    counts: {
      origins: origins.length, routes: routes.length, destinations: destinations.length,
      promotions_live: 1, promotions_expired: 1,
      low_prices: Object.values(lowRows).reduce((n, rows) => n + rows.length, 0),
    },
  };

  mkdirSync(join(dir, "low-prices"), { recursive: true });
  const write = (file: string, json: unknown) => writeFileSync(join(dir, file), JSON.stringify(json));
  write("meta.json", meta);
  writeFileSync(join(dir, "labels.json"), readFileSync(join(FIXTURES_DIR, "labels.json")));
  write("origins.json", { version: 1, origins });
  write("routes.json", { version: 1, routes });
  write("destinations.json", { version: 1, destinations });
  write("promotions.json", { version: 1, promotions });
  for (const [origin, rows] of Object.entries(lowRows)) {
    write(`low-prices/${origin}.json`, {
      version: 1, origin, generated_at: GENERATED_AT, run: 99,
      cols: ["obs", "dest", "price", "dep", "ret", "found", "fetched", "airline", "stops", "airport", "typical", "link", "baggage"],
      rows, truncated: 0,
    });
  }
  return { routes, origins, destinations, dormant: routes.filter((r) => r.status === "dormant") };
}

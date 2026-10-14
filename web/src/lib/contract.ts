// TypeScript shapes of the website data contract v1 (contract/site/v1/*.schema.json, D27).
// The schemas are the source of truth and are enforced at build time by site-data.ts; these
// types only describe what the pages read.

export type Kind = "europe" | "long_haul" | "domestic";

export interface Offer {
  obs: number;
  route: string;
  price: number;
  departure: string;
  return: string;
  nights: number;
  airline: string | null;
  transfers: number | null;
  return_transfers: number | null;
  arrival_airport: string | null;
  found_date: string | null;
  fetched_at: string;
}

export interface Meta {
  version: 1;
  generated_at: string;
  fixture: boolean;
  run: { id: number; finished_at: string | null } | null;
  currency: "EUR";
  base_url: string;
  detector: Record<string, number>;
  files: {
    origins: string; routes: string; destinations: string; promotions: string; labels: string;
    pontes?: string;
    low_prices: Record<string, string>;
  };
  counts: Record<string, number>;
}

export interface Labels {
  version: 1;
  airlines: Record<string, string>;
  airports: Record<string, { name: string; remote: boolean }>;
  kinds: Record<Kind, string>;
  route_status: { active: string; dormant: string };
  months: string[];
  months_short: string[];
  weekdays_short: string[];
  disclosure: { site: string; post: string };
}

export interface Origin {
  iata: string;
  name: string;
  slug: string;
  routes: { active: number; dormant: number };
  low_prices: number;
  promotions_live: number;
}

export interface RouteMonth {
  month: string;
  typical_low: number | null;
  average: number | null;
  days: number;
}

export interface Route {
  key: string;
  origin: string;
  destination: string;
  city: string;
  city_en: string | null;
  kind: Kind;
  status: "active" | "dormant";
  airports: string[];
  rules: { direct_only: boolean; min_nights: number; max_nights: number; max_transfers: number | null };
  path: string;
  months: RouteMonth[];
  cheapest: Offer | null;
  counts: { observations: number; low_prices: number; promotions_live: number; promotions_expired: number };
  discovered_at: string | null;
  last_observed_at: string | null;
}

export interface Photo {
  file: string;
  photographer: string;
  photographer_url: string;
  source: string;
  source_url: string;
  license: string;
}

export interface Destination {
  code: string;
  city: string;
  city_en: string | null;
  slug: string;
  kinds: Kind[];
  airports: string[];
  routes: string[];
  photo: Photo | null;
}

export interface Promotion {
  id: number;
  route: string;
  status: "approved" | "published" | "expired";
  live: boolean;
  path: string;
  offer: Offer;
  typical_low: number | null;
  baseline_days: number;
  discount_pct: number | null;
  rule: "median" | "price_cap";
  detected_at: string;
  approved_at: string | null;
  published_at: string | null;
  checked_at: string;
  booking_link: string | null;
  expired: { reason: string | null; latest: { obs: number; price: number } | null } | null;
  images: { slides: string[]; thumb: string | null; og: string | null } | null;
}

/** One row of low-prices/<ORIGIN>.json, in the order of `cols`. */
export type LowPriceRow = [
  obs: number, dest: string, price: number, dep: string, ret: string, found: string | null,
  fetched: string, airline: string | null, stops: number | null, airport: string | null,
  typical: number, link: string | null,
];

export interface LowPrices {
  version: 1;
  origin: string;
  generated_at: string;
  run: number | null;
  cols: string[];
  rows: LowPriceRow[];
  truncated: number;
}

/** One upcoming long weekend (pontes.json, D31). Dates are ISO calendar dates. */
export interface Ponte {
  slug: string;
  name: string;
  holiday: { date: string; name: string; optional: boolean };
  days_off: { first: string; last: string };
  bridge: string | null;
  window: { start: string; end: string };
  origins: { iata: string; path: string; title: string }[];
}

export interface Pontes {
  version: 1;
  source: string;
  pontes: Ponte[];
}

export interface SiteData {
  meta: Meta;
  labels: Labels;
  origins: { version: 1; origins: Origin[] };
  routes: { version: 1; routes: Route[] };
  destinations: { version: 1; destinations: Destination[] };
  promotions: { version: 1; promotions: Promotion[] };
  lowPrices: Record<string, LowPrices>;
  /** Empty when the export predates pontes.json. */
  pontes: Pontes;
}

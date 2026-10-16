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
  /** A checked bag included (D43), from the GraphQL row matched to the offer; null or absent:
   * unknown, so the page prints no baggage line. */
  baggage?: boolean | null;
}

/** `meta.detector`: the settings typical lows, low prices and promotions were computed with. */
export interface Detector {
  low_threshold: number;
  threshold: number;
  min_saving_eur: number;
  min_baseline_days: number;
  /** Added in v1 (D40): a day counts only with this many departure dates; absent: every day (1). */
  min_dates_per_day?: number;
  max_offer_age_days: number;
  lookback_days: number;
}

export interface Meta {
  version: 1;
  generated_at: string;
  fixture: boolean;
  run: { id: number; finished_at: string | null } | null;
  currency: "EUR";
  base_url: string;
  /** Cloudflare Web Analytics beacon token (D34); null/absent: no beacon. */
  analytics_token?: string | null;
  /** Aviasales search form script src from Travelpayouts' widget constructor (D34). */
  search_widget?: string | null;
  /** "@ondestaanocas": the contact on the About and Privacy pages (D34). */
  instagram_handle?: string;
  detector: Detector;
  files: {
    origins: string; routes: string; destinations: string; promotions: string; labels: string;
    pontes?: string;
    affiliates?: string;
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
  /** affiliate: in every affiliate block (D37); absent in older exports. */
  disclosure: { site: string; post: string; affiliate?: string };
}

export interface Origin {
  iata: string;
  name: string;
  /** The article the name takes in a sentence ("o" Porto, "a" Madeira); null or absent: none. */
  article?: "o" | "a" | "os" | "as" | null;
  slug: string;
  /** The origin page, /partidas/<slug>/ (D30). */
  path: string;
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

/** One day of a route's price calendar: the cheapest fresh offer departing that day (D30). */
export interface CalendarDay {
  dep: string;
  ret: string;
  obs: number;
  price: number;
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
  calendar: CalendarDay[];
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
  /** The destination hub, /destinos/<slug>/ (D30). */
  path: string;
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
  /** Its Instagram post once published (D36); absent in exports before the field existed. */
  post_url?: string | null;
  expired: { reason: string | null; latest: { obs: number; price: number } | null } | null;
  images: { slides: string[]; thumb: string | null; og: string | null } | null;
}

/** One row of low-prices/<ORIGIN>.json, in the order of `cols`. */
export type LowPriceRow = [
  obs: number, dest: string, price: number, dep: string, ret: string, found: string | null,
  fetched: string, airline: string | null, stops: number | null, airport: string | null,
  typical: number, link: string | null, baggage?: boolean | null,
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

/** One long weekend of the holiday calendar (pontes.json, D31), past ones included. Dates are
 * ISO calendar dates. No display text: titles come from format.ts (`ponteTitle`). */
export interface Ponte {
  slug: string;
  name: string;
  holiday: { date: string; name: string; optional: boolean };
  days_off: { first: string; last: string };
  bridge: string | null;
  window: { start: string; end: string };
  origins: { iata: string; path: string }[];
}

export interface Pontes {
  version: 1;
  source: string;
  pontes: Ponte[];
}

/** The affiliate blocks of itineraries and tips (D37). */
export type Programme = "esim" | "insurance" | "activities";

/** affiliates.json (D37): each block programme's brand (null: not configured) and one tracked link
 * per (published article, configured programme its front matter lists). */
export interface Affiliates {
  version: 1;
  programmes: Record<Programme, { brand: string } | null>;
  /** article = "<collection>/<entry id>", e.g. "itineraries/paris-em-3-dias". */
  links: { article: string; programme: Programme; url: string }[];
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
  /** No programme configured and no links when the export predates affiliates.json. */
  affiliates: Affiliates;
}

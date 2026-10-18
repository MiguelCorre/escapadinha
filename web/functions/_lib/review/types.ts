// Shapes the review Function (#9, D29) works with. No runtime dependencies: wrangler bundles
// web/functions/ on its own, without node_modules.
import type { KeyCache } from "./access";

/** The subset of Cloudflare's R2Bucket binding the Function uses (`STORE`). */
export interface Bucket {
  get(key: string): Promise<{ body: ReadableStream; text(): Promise<string>; arrayBuffer(): Promise<ArrayBuffer> } | null>;
  put(key: string, value: string | ArrayBuffer | Uint8Array, options?: unknown): Promise<unknown>;
  list(options: { prefix?: string; cursor?: string; limit?: number }): Promise<{
    objects: { key: string }[]; truncated: boolean; cursor?: string;
  }>;
}

/** Pages project bindings (production environment, set by Miguel in the dashboard). */
export interface Env {
  ACCESS_TEAM_DOMAIN: string;       // pontonomada.cloudflareaccess.com
  ACCESS_AUD: string;               // AUD tag of the Access application protecting /review
  GITHUB_DISPATCH_TOKEN: string;    // fine-grained PAT: Contents read/write on the repository
  TRAVELPAYOUTS_TOKEN: string;
  GITHUB_REPOSITORY?: string;       // owner/name; default MiguelCorre/escapadinha
  STORE: Bucket;                    // R2: the pipeline's bucket (review/snapshot.json, events, slides)
}

/** What the handler needs from the outside world, injected so tests replace it. */
export interface Deps {
  fetch: typeof fetch;
  now: () => Date;
  uuid: () => string;
  keys: KeyCache;
}

// --- contract/review/v1 (the pipeline writes the snapshot, the Function writes events) --------

export type DecisionType = "approve" | "reject" | "published";

/** detector.CONFIDENCE_LEVELS: trust in a typical low (D44). */
export type Confidence = "low" | "medium" | "high";

export interface LiveCheck {
  valid: boolean;
  price_eur: number | null;
  reason: string;
  checked_at: string;
}

export interface ReviewEvent {
  version: 1;
  id: string;
  type: DecisionType;
  deal_id: number;
  created_at: string;
  actor: string;
  note: string | null;
  post_url: string | null;
  live_check: LiveCheck | null;
}

export interface Rules {
  direct_only: boolean;
  max_transfers: number | null;
  min_nights: number;
  max_nights: number;
  max_offer_age_days: number;
}

/** First to last baseline day, and the cheapest and dearest daily low with their observations. */
export interface BaselineRange {
  span_days: number;
  lowest_eur: number;
  lowest_observation_id: number;
  highest_eur: number;
  highest_observation_id: number;
}

export interface SnapshotDeal {
  id: number;
  status: "new" | "rendered" | "approved" | "published" | "rejected" | "expired";
  status_pt: string;
  observation_id: number;
  route: string;
  headline: string;
  arrival_airport: string | null;
  price_eur: number;
  price: string;
  departure_date: string;
  return_date: string;
  dates: string;
  nights: string;
  airline: string | null;
  direct: boolean | null;
  /** Stops each way (null: unknown); absent from snapshots made before they were added. */
  transfers?: number | null;
  return_transfers?: number | null;
  /** GraphQL enrichment (D43): the selling agency and the baggage line ("só bagagem de mão"),
   * null when the offer had no match; absent from older snapshots. */
  gate?: string | null;
  with_baggage?: boolean | null;
  baggage?: string | null;
  rule: string;
  discount_pct: number | null;
  typical_low_eur: number | null;
  baseline_days: number;
  /** How solid the typical low is (D40); null without a stored range, absent before D40. */
  baseline?: BaselineRange | null;
  /** D44: how much the detector trusted the typical low at detection, and whether the price
   * beat everything seen for the route-month ("novo mínimo"). Null for older deals, absent
   * from older snapshots. */
  confidence?: Confidence | null;
  new_low?: boolean | null;
  found_date: string | null;
  found_on: string | null;
  fetched_at: string;
  checked_at: string;
  detected_at: string;
  affiliate_url: string | null;
  affiliate_error: string | null;
  caption: string | null;
  whatsapp_text: string | null;
  page_url: string | null;
  slides: { url: string | null; key: string | null }[];
  live_check: {
    last_checked_at: string | null;
    last_seen_price_eur: number | null;
    expired_reason: string | null;
    query: Record<string, string | number>;
    rules: Rules;
  };
  review_note: string | null;
  reviewed_at: string | null;
  published_at: string | null;
  post_url: string | null;
}

export interface Outcome {
  event_id: string;
  type: DecisionType | null;
  deal_id: number | null;
  actor: string | null;
  outcome: "applied" | "refused" | "malformed";
  reason: string | null;
  settled_at: string;
  status_before: string | null;
  status_after: string | null;
}

export interface Snapshot {
  version: 1;
  generated_at: string;
  site_base_url: string;
  review_rules: { approve_max_age_hours: number };
  queue: SnapshotDeal[];
  approved: SnapshotDeal[];
  published: SnapshotDeal[];
  closed: SnapshotDeal[];
  pending_events: ReviewEvent[];
  recent_outcomes: Outcome[];
}

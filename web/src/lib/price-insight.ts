// The price verdict (D58, #80): "baixo", "habitual" or "alto" for a price against its departure
// month's typical low, and nothing at all when the history is not there. The rule is the site's
// own, so a page can explain it in one line (VERDICT_NOTE): baixo is the low-price tier's rule
// (D24: at most typical low × (1 − low_threshold)), alto is at least meta.detector.high_margin
// above the typical low, habitual in between. A verdict needs a mature month (days ≥
// min_baseline_days) with confidence medium or high (D44); an export from before the field
// existed (no high_margin, no confidence) gets none. The typical low it names carries data-route.
import type { Detector, Route, RouteMonth } from "./contract";

export type Verdict = "baixo" | "habitual" | "alto";

/** The one-line explanation next to every verdict: ours, measured here, not a market average. */
export const VERDICT_NOTE = "comparado com o mínimo habitual que medimos nesta rota para esse mês";

/** The verdict for `price` against `month`, or null when the month cannot judge it. */
export function verdict(price: number, month: RouteMonth | undefined, det: Detector): Verdict | null {
  if (!month || month.typical_low == null || month.days < det.min_baseline_days) return null;
  if (month.confidence !== "medium" && month.confidence !== "high") return null;
  if (det.high_margin == null) return null;
  if (price <= month.typical_low * (1 - det.low_threshold)) return "baixo";
  if (price >= month.typical_low * (1 + det.high_margin)) return "alto";
  return "habitual";
}

/** The route's month entry a departure date belongs to ("2026-12-12" → the "2026-12" row). */
export function monthOf(route: Pick<Route, "months">, departure: string): RouteMonth | undefined {
  return route.months.find((m) => m.month === departure.slice(0, 7));
}

export interface PriceInsight {
  verdict: Verdict;
  month: string;        // "2026-12"
  typicalLow: number;   // the typical low it was judged against (on data-route)
}

/** What a page prints for `price` departing on `departure` on `route`, or null (nothing). */
export function priceInsight(price: number, route: Pick<Route, "months">, departure: string,
  det: Detector): PriceInsight | null {
  const month = monthOf(route, departure);
  const v = verdict(price, month, det);
  if (!v || !month || month.typical_low == null) return null;
  return { verdict: v, month: month.month, typicalLow: month.typical_low };
}

// The price verdict (D58, #80): the three bands at their edges, the months that cannot judge
// (immature, low confidence, no typical low, an export without the fields) and the copy.
import { describe, expect, it } from "vitest";
import type { Detector, RouteMonth } from "../src/lib/contract";
import { priceVerdict } from "../src/lib/format";
import { VERDICT_NOTE, monthOf, priceInsight, verdict } from "../src/lib/price-insight";

const DET: Detector = { low_threshold: 0.15, threshold: 0.3, min_saving_eur: 15, min_baseline_days: 7,
  min_dates_per_day: 2, max_offer_age_days: 3, lookback_days: 90, high_margin: 0.25 };
const MONTH: RouteMonth = { month: "2026-12", typical_low: 100, average: 110, days: 7, confidence: "medium" };

describe("price verdict", () => {
  it("is baixo at the low-price rule, alto at high_margin above the typical low, habitual between", () => {
    expect(verdict(85, MONTH, DET)).toBe("baixo");          // 100 × (1 − 0.15)
    expect(verdict(85.01, MONTH, DET)).toBe("habitual");
    expect(verdict(124.99, MONTH, DET)).toBe("habitual");
    expect(verdict(125, MONTH, DET)).toBe("alto");          // 100 × (1 + 0.25)
    expect(verdict(85, { ...MONTH, confidence: "high" }, DET)).toBe("baixo");
  });

  it("says nothing without a mature month of medium or high confidence", () => {
    expect(verdict(85, { ...MONTH, days: 6 }, DET)).toBeNull();
    expect(verdict(85, { ...MONTH, confidence: "low" }, DET)).toBeNull();
    expect(verdict(85, { ...MONTH, confidence: null }, DET)).toBeNull();
    expect(verdict(85, { ...MONTH, confidence: undefined }, DET)).toBeNull();      // an older export
    expect(verdict(85, { ...MONTH, typical_low: null }, DET)).toBeNull();
    expect(verdict(85, undefined, DET)).toBeNull();
    expect(verdict(85, MONTH, { ...DET, high_margin: undefined })).toBeNull();     // an older export
  });

  it("judges a departure date against its own month's row", () => {
    const route = { months: [{ ...MONTH, month: "2026-11", typical_low: 50 }, MONTH] };
    expect(monthOf(route, "2026-12-12")).toBe(MONTH);
    expect(monthOf(route, "2027-01-03")).toBeUndefined();
    expect(priceInsight(85, route, "2026-12-12", DET)).toEqual({ verdict: "baixo", month: "2026-12", typicalLow: 100 });
    expect(priceInsight(85, route, "2026-11-12", DET)).toEqual({ verdict: "alto", month: "2026-11", typicalLow: 50 });
    expect(priceInsight(85, route, "2027-01-03", DET)).toBeNull();
  });

  it("has its words in format.ts and one plain explanation", () => {
    expect(priceVerdict("baixo", "2026-12")).toBe("Preço baixo para dezembro");
    expect(priceVerdict("habitual", "2027-02")).toBe("Preço habitual para fevereiro");
    expect(priceVerdict("alto", "2026-11")).toBe("Preço alto para novembro");
    expect(VERDICT_NOTE).toBe("comparado com o mínimo habitual que medimos nesta rota para esse mês");
  });
});

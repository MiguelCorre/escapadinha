// The promotion's Offer (JSON-LD) carries the price the page shows: after a recheck that held the
// promotion through a small rise (D53), that is the latest verified price on its observation,
// not the detection's offer. One rule, `promotionView`, feeds the summary, the verdict and the
// Trip (D62 review fix).
import { describe, expect, it } from "vitest";
import { promotionView } from "../src/lib/promotion";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { promotionLd } from "../src/lib/structured-data";

const data = loadSiteData(FIXTURES_DIR);
const live = data.promotions.promotions.find((p) => p.live && p.promotion?.lead !== false)!;

describe("promotionLd", () => {
  it("offers the latest verified price when a recheck moved it, on that observation", () => {
    const moved = { ...live, latest: { obs: 99_999, price: live.offer.price + 2 } };
    const view = promotionView(data, moved);
    expect(view.obs).toBe(99_999);
    expect(view.priceEur).toBe(live.offer.price + 2);
    const trip = promotionLd(data, moved, view, "x")!;
    expect(trip.offers).toMatchObject({ price: live.offer.price + 2, priceCurrency: "EUR" });
  });

  it("offers the detection's price before any recheck, and nothing once expired", () => {
    const fresh = { ...live, latest: null };
    const view = promotionView(data, fresh);
    expect(view.priceEur).toBe(live.offer.price);
    expect(promotionLd(data, fresh, view, "x")!.offers).toMatchObject({ price: live.offer.price });
    expect(promotionLd(data, { ...live, live: false }, view, "x")).toBeNull();
  });
});

// The booking-button rule every page shares (src/lib/cta.ts).
import { describe, expect, it } from "vitest";
import { bookingCta } from "../src/lib/cta";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";

const { labels } = loadSiteData(FIXTURES_DIR);
const LINK = "https://example.com/parceiro/site-deal-3";

describe("bookingCta", () => {
  it("gives a live price with a link a sponsored button and the site disclosure", () => {
    const cta = bookingCta(LINK, true, labels)!;
    expect(cta.href).toBe(LINK);
    expect(cta.rel.split(" ")).toEqual(expect.arrayContaining(["sponsored", "nofollow"]));
    expect(cta.disclosure).toBe(labels.disclosure.site);
  });

  it("gives no button when the price is not live or there is no link", () => {
    expect(bookingCta(LINK, false, labels)).toBeNull();
    expect(bookingCta(null, true, labels)).toBeNull();
  });
});

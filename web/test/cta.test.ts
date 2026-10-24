// The booking-button rule every page shares (src/lib/cta.ts).
import { describe, expect, it } from "vitest";
import { airlineNote, bookingCta, bookingLink, CTA_NOTE, CTA_TEXT } from "../src/lib/cta";
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

  it("gives an airline's own link the airline note and the direct disclosure (D47)", () => {
    const direct = "Ligação direta ao site da companhia aérea: não recebemos comissão por esta reserva.";
    const withDirect = { ...labels, disclosure: { ...labels.disclosure, direct } };
    const link = "https://www.ryanair.com/pt/pt/trip/flights/select?dateOut=2026-11-19";
    const cta = bookingCta(link, true, withDirect, "airline", "Ryanair")!;
    expect(cta.href).toBe(link);
    expect(cta.note).toBe(airlineNote("Ryanair"));
    expect(cta.note).toContain("site da Ryanair");
    expect(cta.disclosure).toBe(direct);
    // the partner kind is the default and unchanged
    expect(bookingCta(LINK, true, withDirect)).toMatchObject({ note: CTA_NOTE, disclosure: labels.disclosure.site });
    // an export without the direct label (one made before D47) cannot show an airline button honestly
    const { direct: _direct, ...older } = labels.disclosure;
    expect(() => bookingCta(link, true, { ...labels, disclosure: older }, "airline", "Ryanair")).toThrow(/disclosure.direct/);
    expect(bookingCta(link, false, withDirect, "airline", "Ryanair")).toBeNull();
  });

  it("gives no button when the price is not live or there is no link", () => {
    expect(bookingCta(LINK, false, labels)).toBeNull();
    expect(bookingCta(null, true, labels)).toBeNull();
  });

  it("is the one button rule for lists too: https only, the same text and rel", () => {
    expect(bookingLink(LINK)).toEqual({ href: LINK, text: CTA_TEXT, rel: "sponsored nofollow noopener" });
    expect(bookingLink(null)).toBeNull();
    expect(() => bookingLink("http://example.com/x")).toThrow(/not https/);
    expect(() => bookingCta("http://example.com/x", true, labels)).toThrow(/not https/);
  });
});

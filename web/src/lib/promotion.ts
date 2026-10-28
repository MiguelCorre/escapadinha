// What a promotion card or page shows, derived from the contract the way presentation.py builds a
// DealView for the slides: the remote arrival airport in the headline, pt-PT formats, found date
// (traveller) kept apart from our check (D10, D11).
import type { Offer, Promotion, SiteData } from "./contract";
import {
  baggageText, dateRange, discountParts, eur, eurParts, lisbonTimestamp, monthName, nights, numericDate,
  shortDate, type DiscountParts, type EurParts,
} from "./format";

export interface Place {
  originName: string;
  city: string;
  arrivalCode: string | null;
  arrivalName: string | null;   // "Beauvais"; null when the code is unknown or absent
  remote: boolean;
  /** "Lisboa → Paris (Beauvais)" for a remote airport, else "Lisboa → Paris". */
  headline: string;
}

export function place(data: SiteData, offer: Offer): Place {
  const [origin, destination] = offer.route.split("-");
  const originName = data.origins.origins.find((o) => o.iata === origin)?.name ?? origin;
  const city = data.routes.routes.find((r) => r.key === offer.route)?.city
    ?? data.destinations.destinations.find((d) => d.code === destination)?.city
    ?? destination;
  const code = offer.arrival_airport;
  const airport = code ? data.labels.airports[code] : undefined;
  const remote = airport?.remote ?? false;
  return {
    originName, city, arrivalCode: code, arrivalName: airport?.name ?? null, remote,
    headline: `${originName} → ${city}${remote ? ` (${airport!.name})` : ""}`,
  };
}

/** "Beauvais (BVA)"; the bare code when we have no name for it. */
export function airportLabel(p: Place): string | null {
  if (!p.arrivalCode) return null;
  return p.arrivalName ? `${p.arrivalName} (${p.arrivalCode})` : p.arrivalCode;
}

function leg(n: number | null): string | null {
  if (n == null) return null;
  return n === 0 ? "direto" : n === 1 ? "1 escala" : `${n} escalas`;
}

/** "Diretos, ida e volta" / "Ida direto, regresso 1 escala"; null when unknown. */
export function stops(offer: Offer): string | null {
  const out = leg(offer.transfers);
  const back = leg(offer.return_transfers);
  if (!out || !back) return null;
  if (offer.transfers === 0 && offer.return_transfers === 0) return "Diretos, ida e volta";
  return `Ida ${out}, regresso ${back}`;
}

export interface PromotionView extends Place {
  id: number;
  obs: number;
  path: string;
  live: boolean;
  price: EurParts;            // {amount: "86", currency: "€", text: "86 €"}
  /** {sign: "−", value: "44%", text: "−44%"}; median rule only (no "% below" claim without a
   * typical low). */
  discount: DiscountParts | null;
  typicalLow: string | null;  // "153,50 €"
  month: string;              // "dezembro" (departure month the typical low is about)
  dates: string;              // "qua, 9 dez → sex, 11 dez"
  datesProse: string;         // "9 a 11 de dezembro"
  nights: string;             // "2 noites"
  airline: string | null;
  stops: string | null;
  baggage: string | null;     // "só bagagem de mão"; null when unknown (no line, D43)
  foundOn: string | null;     // "12/10/2026": when a traveller found the price
  checkedAt: string;          // ours: last recheck, else first fetch, Lisbon time ("verificado a")
  expiredReason: string | null;
  expiredObs: number | null;  // the observation behind the price in the reason
  /** The one-line summary deals sites lead with (D46): "Voos diretos por 69 € ida e volta, com a
   * Ryanair, só bagagem de mão." The price sits between `before` and `after`, so the page can put
   * it on its data-obs. `after` ends with the full stop. */
  summary: { before: string; after: string };
  routesLine: string;         // "Lisboa – Madeira (FNC) – Lisboa"
  publishedOn: string | null; // when it went live on the site (approved_at, Lisbon time)
}

/** "Voos diretos" when nonstop both ways, "Voos" otherwise (unknown stops included). */
function flightsWord(offer: Offer): string {
  return offer.transfers === 0 && offer.return_transfers === 0 ? "Voos diretos" : "Voos";
}

export function summaryParts(offer: Offer, airline: string | null, baggage: string | null): { before: string; after: string } {
  const extras = [airline && `com a ${airline}`, baggage].filter(Boolean).join(", ");
  return { before: `${flightsWord(offer)} por`, after: `ida e volta${extras ? `, ${extras}` : ""}.` };
}

export function routesLine(p: Place): string {
  const there = `${p.city}${p.arrivalCode ? ` (${p.arrivalCode})` : ""}`;
  return `${p.originName} – ${there} – ${p.originName}`;
}

/** The items that are pages (D53): ungrouped ones and the lead of every promotion. */
export function pagePromotions(data: SiteData): Promotion[] {
  return data.promotions.promotions.filter((p) => !p.promotion || p.promotion.lead);
}

/** The live dates of a promotion page, cheapest first, the lead among them (D53); an ungrouped
 * item is its own only date. Each is an item of the contract with its own offer and `obs`. */
export function promotionDates(data: SiteData, lead: Promotion): Promotion[] {
  if (!lead.promotion) return [lead];
  const byId = new Map(data.promotions.promotions.map((p) => [p.id, p]));
  return lead.promotion.dates.map((id) => byId.get(id)).filter((p): p is Promotion => p !== undefined);
}

export function promotionView(data: SiteData, p: Promotion): PromotionView {
  const o = p.offer;
  const where = place(data, o);
  const airline = o.airline ? data.labels.airlines[o.airline] ?? o.airline : null;
  const baggage = baggageText(o.baggage);
  return {
    ...where,
    id: p.id,
    obs: o.obs,
    path: p.path,
    live: p.live,
    price: eurParts(o.price),
    discount: p.rule === "median" && p.discount_pct != null ? discountParts(p.discount_pct) : null,
    typicalLow: p.typical_low != null ? eur(p.typical_low) : null,
    month: monthName(o.departure),
    dates: `${shortDate(o.departure)} → ${shortDate(o.return)}`,
    datesProse: dateRange(o.departure, o.return),
    nights: nights(o.nights),
    airline,
    stops: stops(o),
    baggage,
    foundOn: o.found_date ? numericDate(o.found_date) : null,
    checkedAt: lisbonTimestamp(p.checked_at),
    expiredReason: p.expired?.reason ?? null,
    expiredObs: p.expired?.latest?.obs ?? null,
    summary: summaryParts(o, airline, baggage),
    routesLine: routesLine(where),
    publishedOn: p.approved_at ? lisbonTimestamp(p.approved_at) : null,
  };
}

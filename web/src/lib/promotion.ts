// What a promotion card or page shows, derived from the contract the way presentation.py builds a
// DealView for the slides: the remote arrival airport in the headline, pt-PT formats, found date
// (traveller) kept apart from our check (D10, D11).
import type { Offer, Promotion, SiteData } from "./contract";
import {
  dateRange, discount, eur, lisbonTimestamp, monthName, nights, numericDate, shortDate,
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
  price: string;              // "86 €"
  discount: string | null;    // "−44%" (median rule only: no "% below" claim without a typical low)
  typicalLow: string | null;  // "153,50 €"
  month: string;              // "dezembro" (departure month the typical low is about)
  dates: string;              // "qua, 9 dez → sex, 11 dez"
  datesProse: string;         // "9 a 11 de dezembro"
  nights: string;             // "2 noites"
  airline: string | null;
  stops: string | null;
  foundOn: string | null;     // "12/10/2026": when a traveller found the price
  fetchedAt: string;          // when our collection first saw it, Lisbon time
  checkedAt: string;          // last recheck, Lisbon time ("verificado a")
  expiredReason: string | null;
  expiredObs: number | null;  // the observation behind the price in the reason
}

export function promotionView(data: SiteData, p: Promotion): PromotionView {
  const o = p.offer;
  return {
    ...place(data, o),
    id: p.id,
    obs: o.obs,
    path: p.path,
    live: p.live,
    price: eur(o.price),
    discount: p.rule === "median" && p.discount_pct != null ? discount(p.discount_pct) : null,
    typicalLow: p.typical_low != null ? eur(p.typical_low) : null,
    month: monthName(o.departure),
    dates: `${shortDate(o.departure)} → ${shortDate(o.return)}`,
    datesProse: dateRange(o.departure, o.return),
    nights: nights(o.nights),
    airline: o.airline ? data.labels.airlines[o.airline] ?? o.airline : null,
    stops: stops(o),
    foundOn: o.found_date ? numericDate(o.found_date) : null,
    fetchedAt: lisbonTimestamp(o.fetched_at),
    checkedAt: lisbonTimestamp(p.checked_at),
    expiredReason: p.expired?.reason ?? null,
    expiredObs: p.expired?.latest?.obs ?? null,
  };
}

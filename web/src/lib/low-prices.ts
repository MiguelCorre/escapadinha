// One view of a low price (D24), shared by every list that shows them: the route pages
// (LowPriceList.astro), the explorer and the ponte pages (ExplorerResults.astro) and the explorer's
// island, so a row reads the same everywhere, with and without JavaScript. Pure and browser-safe.
// Rows are low-prices/<ORIGIN>.json rows as the contract gives them; the price keeps `data-obs`
// and the typical low `data-route` (D2). The booking button follows src/lib/cta.ts; a row without
// a stored partner link (per-run link budget, D24) says the link is coming instead.
import type { LowPriceRow } from "./contract";
import { bookingLink, NO_LINK_NOTE, type BookingLink } from "./cta";
import { daysBetween } from "./dates";
import {
  count, discountParts, eur, eurParts, lisbonTimestamp, monthName, nights, numericDate, shortDate,
  stopsText, type EurParts,
} from "./format";

/** What a row needs besides itself: names of its destination, arrival airport and airline. */
export interface Places {
  origin: string;
  cities: Record<string, string>;
  airports: Record<string, { name: string; remote: boolean }>;
  airlines: Record<string, string>;
  /** Destination code -> its route page, the contract's `path` (D30); no link without one. */
  paths?: Record<string, string>;
}

/** A row and how many other matching dates its destination has (the explorer's "+N datas"). */
export interface LowPriceItem {
  row: LowPriceRow;
  more: number;
}

export interface LowPriceView {
  obs: number;
  route: string;              // "LIS-PAR" (data-route of the typical low)
  headline: string;           // "Paris (Beauvais)": a remote arrival airport in the headline
  path: string | null;        // the route page
  price: EurParts;
  discount: string | null;    // "−32%" below the typical low
  typicalLow: string;         // the departure month's typical low
  month: string;              // "novembro"
  dates: string;              // "sáb, 14 nov → ter, 17 nov"
  nights: string;             // "3 noites"
  airline: string | null;     // "Ryanair"
  stops: string | null;       // "voos diretos", "1 escala"; null when unknown
  airport: string | null;     // "Beauvais (BVA)"
  remote: boolean;
  foundOn: string | null;     // the traveller's found date (found_date)
  fetchedAt: string;          // our first sight, Lisbon time (fetched_at)
  more: number;
  link: BookingLink | null;   // null: no stored partner link yet
}

export function lowPriceView({ row, more }: LowPriceItem, places: Places): LowPriceView {
  const [obs, dest, price, dep, ret, found, fetched, airline, stops, airport, typical, link] = row;
  const city = places.cities[dest] ?? dest;
  const known = airport ? places.airports[airport] : undefined;
  const remote = known?.remote ?? false;
  return {
    obs, route: `${places.origin}-${dest}`,
    headline: remote ? `${city} (${known!.name})` : city,
    path: places.paths?.[dest] ?? null,
    price: eurParts(price),
    discount: typical > price ? discountParts(1 - price / typical).text : null,
    typicalLow: eur(typical), month: monthName(dep),
    dates: `${shortDate(dep)} → ${shortDate(ret)}`, nights: nights(daysBetween(dep, ret)),
    airline: airline ? places.airlines[airline] ?? airline : null,
    stops: stopsText(stops),
    airport: airport ? (known ? `${known.name} (${airport})` : airport) : null,
    remote,
    foundOn: found ? numericDate(found) : null,
    fetchedAt: lisbonTimestamp(fetched),
    more,
    link: bookingLink(link),
  };
}

const ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(value: string | number): string {
  return String(value).replace(/[&<>"']/g, (c) => ESC[c]);
}

/** One <li>. `headline`: the destination as an <h3> (lists of many destinations); a route page
 * already names it. The list's [data-cta] block carries the site disclosure and CTA_NOTE once. */
export function lowPriceHtml(v: LowPriceView, { headline }: { headline: boolean }): string {
  const muted = (html: string) => `<p class="text-small text-muted">${html}</p>`;
  const title = v.path
    ? `<a class="text-ink no-underline hover:underline" href="${esc(v.path)}">${esc(v.headline)}</a>`
    : esc(v.headline);
  const carrier = [v.airline, v.stops].filter(Boolean).join(" · ");
  const found = v.foundOn
    ? `Encontrado por um viajante a <span class="num font-semibold text-ink">${esc(v.foundOn)}</span> · `
    : "";
  return [
    `<li data-obs="${esc(v.obs)}" data-route="${esc(v.route)}" class="flex flex-col gap-xs border-t-[3px] border-double border-ink bg-surface p-md">`,
    headline ? `<h3 class="font-display text-title">${title}</h3>` : "",
    `<div class="flex flex-wrap items-end gap-x-md gap-y-xs">`,
    `<p data-obs="${esc(v.obs)}" class="font-display num text-price text-ink">${esc(v.price.amount)}<span class="price-sign"> ${v.price.currency}</span></p>`,
    v.discount ? `<p class="pb-2xs"><span class="tag tag-success num">${esc(v.discount)}</span></p>` : "",
    `</div>`,
    muted("ida e volta, por pessoa"),
    `<p class="font-semibold num">${esc(v.dates)} <span class="font-normal text-muted">· ${esc(v.nights)}</span></p>`,
    carrier ? muted(esc(carrier)) : "",
    v.airport ? muted(`Chegada: ${esc(v.airport)}${v.remote ? ' <span class="tag tag-warning">longe do centro</span>' : ""}`) : "",
    muted(`Mínimo habitual em ${esc(v.month)}: <span data-route="${esc(v.route)}" class="num">${esc(v.typicalLow)}</span>`),
    muted(`${found}visto por nós a <span class="num">${esc(v.fetchedAt)}</span>`),
    v.more ? muted(`Mais ${esc(count(v.more, "data", "datas"))} com preço baixo`) : "",
    v.link
      ? `<a class="btn mt-xs self-start" href="${esc(v.link.href)}" rel="${v.link.rel}" target="_blank">${v.link.text} →</a>`
      : `<p data-no-link class="text-small text-muted">${NO_LINK_NOTE}</p>`,
    `</li>`,
  ].join("");
}

/** The <li> items of a list of low prices (the page wraps them in its <ul>). */
export function lowPricesHtml(items: LowPriceItem[], places: Places, options: { headline: boolean }): string {
  return items.map((item) => lowPriceHtml(lowPriceView(item, places), options)).join("");
}

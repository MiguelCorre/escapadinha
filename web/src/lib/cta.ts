// The one rule for booking buttons, shared by every page that shows one (promotions, low prices
// on route pages, the explorer and its island, the ponte pages): the link comes from the contract
// as given (the partner links API, never built here: no `marker=` URLs, D19) and must be https, a
// button only when there is a link and the price is live, and always the site disclosure from
// labels.json next to it (once per list for lists of low prices).
import type { Labels } from "./contract";

export const CTA_TEXT = "Ver voo e reservar";
export const CTA_REL = "sponsored nofollow noopener";
export const CTA_NOTE = "Abre o site parceiro (Aviasales) em euros. O preço pode já ter mudado: "
  + "confirma o valor final, a bagagem incluída e o aeroporto antes de pagar.";
/** In place of the button when a low price has no stored partner link yet: links are created a
 * few hundred per collection run (D24's link budget), so it comes with a later run. */
export const NO_LINK_NOTE = "Ligação de reserva disponível em breve.";

/** The button itself: the contract's link with our text and rel. */
export interface BookingLink {
  href: string;
  text: string;
  rel: string;
}

export interface Cta extends BookingLink {
  note: string;
  disclosure: string;
}

/** Any partner link from the contract as an anchor's href and rel (booking buttons, the affiliate
 * blocks of D37): as given, never built here. Throws on a non-https link. */
export function partnerLink(link: string): { href: string; rel: string } {
  if (!link.startsWith("https://")) throw new Error(`partner link is not https: ${link}`);
  return { href: link, rel: CTA_REL };
}

/** The button for a link from the contract, or null without one. Throws on a non-https link. */
export function bookingLink(link: string | null): BookingLink | null {
  return link ? { ...partnerLink(link), text: CTA_TEXT } : null;
}

/** The booking button for a price, or null: no link, or not live (expired: never a button). */
export function bookingCta(link: string | null, live: boolean, labels: Labels): Cta | null {
  const button = live ? bookingLink(link) : null;
  return button && { ...button, note: CTA_NOTE, disclosure: labels.disclosure.site };
}

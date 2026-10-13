// The one rule for booking buttons, shared by every page that shows one (promotions now, low
// prices on route pages and the explorer later): the link comes from the contract as given (the
// partner links API, never built here: no `marker=` URLs, D19), a button only when there is a link
// and the price is live, and always the site disclosure from labels.json next to it.
import type { Labels } from "./contract";

export const CTA_TEXT = "Ver voo e reservar";
export const CTA_REL = "sponsored nofollow noopener";
export const CTA_NOTE = "Abre o site parceiro (Aviasales) em euros. O preço pode já ter mudado: "
  + "confirma o valor final, a bagagem incluída e o aeroporto antes de pagar.";

export interface Cta {
  href: string;
  text: string;
  rel: string;
  note: string;
  disclosure: string;
}

/** The booking button for a price, or null: no link, or not live (expired: never a button). */
export function bookingCta(link: string | null, live: boolean, labels: Labels): Cta | null {
  if (!live || !link) return null;
  if (!link.startsWith("https://")) throw new Error(`booking link is not https: ${link}`);
  return { href: link, text: CTA_TEXT, rel: CTA_REL, note: CTA_NOTE, disclosure: labels.disclosure.site };
}

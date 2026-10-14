// JSON-LD for the pages (D34), built from the contract and the reviewed content only. Typed with
// schema-dts (the schema.org vocabulary as TypeScript types, pinned), so `npm run typecheck` fails
// on a property schema.org doesn't define or a value of the wrong type; web/test/jsonld.ts then
// validates every block of the built site at runtime. No value is made up: a promotion's price is
// its offer's (the block carries the offer's data-obs and data-deal, so the traceability test
// checks it), an article's dateModified is its last_checked day.
import type {
  Airport, Article, BreadcrumbList, Organization, Trip, WebSite, WithContext,
} from "schema-dts";
import type { Promotion, SiteData } from "./contract";
import { BRAND } from "./brand";
import type { PromotionView } from "./promotion";

export const CONTEXT = "https://schema.org" as const;

/** The site's own pages: "https://pontonomada.pt" + "/voos/lisboa-paris/". */
const url = (base: string, path: string) => `${base}${path}`;

export function instagramUrl(handle: string | undefined): string | null {
  return handle ? `https://www.instagram.com/${handle.replace(/^@/, "")}/` : null;
}

function organization(data: SiteData): Exclude<Organization, string> {
  const instagram = instagramUrl(data.meta.instagram_handle);
  return {
    "@type": "Organization",
    name: BRAND,
    url: url(data.meta.base_url, "/"),
    ...(instagram ? { sameAs: [instagram] } : {}),
  };
}

export function organizationLd(data: SiteData): WithContext<Organization> {
  return { "@context": CONTEXT, ...organization(data) };
}

export function websiteLd(data: SiteData): WithContext<WebSite> {
  return {
    "@context": CONTEXT,
    "@type": "WebSite",
    name: BRAND,
    url: url(data.meta.base_url, "/"),
    inLanguage: "pt-PT",
    publisher: organization(data),
  };
}

function airport(iataCode: string, name: string): Airport {
  return { "@type": "Airport", iataCode, name };
}

/** A live promotion as a round Trip (out and back as subTrips) with its Offer; null when the
 * promotion is not live (an expired one offers nothing). */
export function promotionLd(data: SiteData, promotion: Promotion, view: PromotionView, description: string)
  : WithContext<Trip> | null {
  if (!promotion.live) return null;
  const o = promotion.offer;
  const [origin] = o.route.split("-");
  const page = url(data.meta.base_url, promotion.path);
  const from = airport(origin, view.originName);
  const to = airport(view.arrivalCode ?? o.route.split("-")[1], view.arrivalName ?? view.city);
  return {
    "@context": CONTEXT,
    "@type": "Trip",
    name: view.headline,
    description,
    url: page,
    tripOrigin: from,
    itinerary: to,
    subTrip: [
      { "@type": "Trip", name: "Ida", departureTime: o.departure, tripOrigin: from, itinerary: to },
      { "@type": "Trip", name: "Regresso", departureTime: o.return, tripOrigin: to, itinerary: from },
    ],
    offers: { "@type": "Offer", price: o.price, priceCurrency: "EUR", url: page },
  };
}

export interface ArticleInput {
  title: string;
  description: string;
  path: string;
  lastChecked?: string;
}

/** An itinerary or tip by Ponto Nómada; null without a checked date (a draft). */
export function articleLd(data: SiteData, a: ArticleInput): WithContext<Article> | null {
  if (!a.lastChecked) return null;
  const page = url(data.meta.base_url, a.path);
  return {
    "@context": CONTEXT,
    "@type": "Article",
    headline: a.title,
    description: a.description,
    inLanguage: "pt-PT",
    dateModified: a.lastChecked,
    author: organization(data),
    publisher: organization(data),
    mainEntityOfPage: page,
    url: page,
    image: url(data.meta.base_url, "/og-default.png"),
  };
}

export interface Crumb {
  name: string;
  path: string;
}

export function breadcrumbLd(data: SiteData, crumbs: Crumb[]): WithContext<BreadcrumbList> {
  return {
    "@context": CONTEXT,
    "@type": "BreadcrumbList",
    itemListElement: crumbs.map((c, i) => ({
      "@type": "ListItem", position: i + 1, name: c.name, item: url(data.meta.base_url, c.path),
    })),
  };
}

/** JSON for a <script type="application/ld+json">: "<" escaped so no "</script>" can end it. */
export function jsonLdText(value: object): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

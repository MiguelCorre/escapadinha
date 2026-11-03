// Which route pages and destination hubs search engines may index (#76, amending D34): only those
// with data of their own. Google's spam policies judge generated pages by their value; a route
// page with no price, no calendar, no typical low and no promotion has none, so it stays online
// (old links keep working, D35) as noindex, and the sitemap leaves it out by itself (sitemap.ts
// reads the built pages). Decided from the contract alone: a route's first price makes its page
// indexable at the next build.
import type { Route } from "./contract";

type Shown = Pick<Route, "cheapest" | "calendar" | "months" | "counts">;

/** A route page shows a price found now, a calendar day, a typical low (the export leaves
 * `typical_low` null below min_baseline_days, D40), or a promotion live or still kept. */
export function routeIndexable(route: Shown): boolean {
  return route.cheapest != null
    || route.calendar.length > 0
    || route.months.some((m) => m.typical_low != null)
    || route.counts.promotions_live + route.counts.promotions_expired > 0;
}

/** A hub has a route page worth indexing, or a reviewed itinerary for the city (D33: content of
 * its own; `itineraryFor` over the review-gated collection). */
export function hubIndexable(routes: readonly Shown[], hasItinerary: boolean): boolean {
  return hasItinerary || routes.some(routeIndexable);
}

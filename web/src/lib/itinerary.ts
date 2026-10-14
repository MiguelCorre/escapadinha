// Route pages and destination hubs link the destination's itinerary when there is one
// (ItineraryLink.astro, D30's hook). The entries are the `itineraries` collection after the review
// gate (src/collections.ts: reviewed only, drafts too in the dev server); this module stays free
// of astro:content so vitest and tsc check it.
import { contentPath } from "./content";

export interface ItineraryRef {
  /** Site path of the itinerary page, e.g. "/roteiros/paris-em-3-dias/". */
  path: string;
  /** Its title, e.g. "Paris em 3 dias". */
  title: string;
}

export interface ItineraryEntry {
  id: string;
  data: { title: string; destination: string; reviewed: boolean };
}

/** The itinerary for a destination city code, or null. One reviewed itinerary per city: two stop
 * the build. In the dev server a draft shows only where no reviewed one exists. */
export function itineraryFor(destination: string, entries: readonly ItineraryEntry[]): ItineraryRef | null {
  const mine = entries.filter((e) => e.data.destination === destination);
  const reviewed = mine.filter((e) => e.data.reviewed);
  if (reviewed.length > 1) {
    throw new Error(`two reviewed itineraries for ${destination}: ${reviewed.map((e) => e.id).join(", ")}`);
  }
  const entry = reviewed[0] ?? mine[0];
  return entry ? { path: contentPath("itineraries", entry.id), title: entry.data.title } : null;
}

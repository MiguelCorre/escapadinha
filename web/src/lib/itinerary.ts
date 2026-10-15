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
  data: { title: string; destination: string; reviewed: boolean; fixture: boolean };
}

/** The itinerary for a destination city code, or null. One reviewed itinerary per city: two stop
 * the build. A test-only one (`fixture: true`) wins over a real one: the review gate passes
 * test-only entries only in a fixture build, so approving a real itinerary for a city the test
 * content uses never breaks it (two real or two test-only ones still stop the build). In the dev
 * server a draft shows only where no reviewed one exists. */
export function itineraryFor(destination: string, entries: readonly ItineraryEntry[]): ItineraryRef | null {
  const mine = entries.filter((e) => e.data.destination === destination);
  const reviewed = (fixture: boolean) => {
    const found = mine.filter((e) => e.data.reviewed && e.data.fixture === fixture);
    if (found.length > 1) {
      throw new Error(`two reviewed itineraries for ${destination}: ${found.map((e) => e.id).join(", ")}`);
    }
    return found[0];
  };
  const real = reviewed(false);
  const entry = reviewed(true) ?? real ?? mine[0];
  return entry ? { path: contentPath("itineraries", entry.id), title: entry.data.title } : null;
}

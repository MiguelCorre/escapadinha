// The hook for #17 (itineraries as reviewed MDX content): route pages and destination hubs ask for
// the destination's itinerary here and link it when there is one (ItineraryLink.astro). Until the
// content collection exists there is none, so nothing is rendered. #17 replaces the body with a
// lookup in the `itineraries` collection (reviewed entries only, by destination code); the
// callers and the component stay as they are.

export interface ItineraryRef {
  /** Site path of the itinerary page, e.g. "/roteiros/paris-em-3-dias/". */
  path: string;
  /** Its title, e.g. "Paris em 3 dias". */
  title: string;
}

/** The reviewed itinerary for a destination city code, or null (always null before #17). */
export function itineraryFor(_destination: string): ItineraryRef | null {
  return null;
}

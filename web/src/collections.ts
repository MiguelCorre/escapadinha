// The review gate applied to the content collections (D33): what the pages, the listings and the
// itinerary links read. Reviewed entries only; drafts too in `astro dev`; test-only entries only
// when the site is built from fixture data. A future sitemap must list these and nothing else.
// (Outside src/lib because astro:content exists only inside an Astro build.)
import { getCollection } from "astro:content";
import data from "virtual:site-data";
import { byLastChecked, isVisible, type BuildMode } from "./lib/content";

// `astro dev` runs in mode "development", `astro build` in "production". Not import.meta.env.DEV:
// Vite derives that from NODE_ENV, which vitest sets to "test", so a test build would show drafts.
const MODE: BuildMode = {
  dev: import.meta.env.MODE === "development",
  fixtureBuild: data.meta.fixture === true,
};

export async function itineraries() {
  return (await getCollection("itineraries", (e) => isVisible(e.data, MODE))).sort(byLastChecked);
}

export async function tips() {
  return (await getCollection("tips", (e) => isVisible(e.data, MODE))).sort(byLastChecked);
}

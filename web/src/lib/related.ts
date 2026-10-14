// Tips related to a destination (spec story 36, #14 "related content"): the destination hub lists
// the tips whose front matter names its city code in `destinations` (src/lib/content.ts). The
// entries are the `tips` collection after the review gate (src/collections.ts: reviewed only,
// drafts too in the dev server); this module stays free of astro:content so vitest and tsc check it.
import { byLastChecked, contentPath } from "./content";

export interface TipRef {
  /** Site path of the tip, e.g. "/dicas/voos-baratos/". */
  path: string;
  title: string;
  description: string;
}

export interface TipEntry {
  id: string;
  data: { title: string; description: string; destinations: string[]; last_checked?: string };
}

/** The tips about a destination city code, most recently checked first; [] when none. */
export function tipsFor(destination: string, entries: readonly TipEntry[]): TipRef[] {
  return entries
    .filter((e) => e.data.destinations.includes(destination))
    .sort(byLastChecked)
    .map((e) => ({ path: contentPath("tips", e.id), title: e.data.title, description: e.data.description }));
}

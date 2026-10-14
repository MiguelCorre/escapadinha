// Itineraries and tips (#17, D33): hand-written MDX in src/content/{itineraries,tips}/ with this
// front matter, read by the content collections (src/content.config.ts). Nothing here touches
// astro:content, so the gate and the schemas are plain modules vitest and tsc check.
//
// Review gate: only `reviewed: true` entries are built and listed; drafts show in the local dev
// server only. A reviewed entry must say when its facts were last checked and link at least one
// official source. Test-only entries (`fixture: true`, under test/fixtures/content/) are built
// only from fixture data, never from a real export. No prices in content (D33): the pt-PT lint
// refuses euro amounts, prices come from the data contract with their observation.
import { z } from "astro/zod";

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** YAML reads `2026-10-14` as a Date: keep it as the ISO day the format helpers take. */
const isoDay = z.union([z.date(), z.string().regex(ISO_DAY)])
  .transform((d) => (typeof d === "string" ? d : d.toISOString().slice(0, 10)));

const source = z.object({
  /** What the link is, e.g. "Turismo de Paris (site oficial)". */
  title: z.string().min(1),
  url: z.url({ protocol: /^https$/ }),
});

const cityCode = z.string().regex(/^[A-Z]{3}$/, "a city code such as PAR");

const common = {
  title: z.string().min(1),
  /** One or two sentences for the listing and the meta description. */
  description: z.string().min(1).max(200),
  /** The day a human last checked every fact against the sources. */
  last_checked: isoDay.optional(),
  sources: z.array(source).default([]),
  /** Months 1-12 when the trip or the tip fits best. */
  best_months: z.array(z.int().min(1).max(12)).default([]),
  reviewed: z.boolean().default(false),
  /** Test-only content (test/fixtures/content/): built from fixture data only, never deployed. */
  fixture: z.boolean().default(false),
  /** The old Jinja site's path of this content (e.g. /guias/<slug>/), for the cutover's 301. */
  legacy_path: z.string().regex(/^\/[a-z0-9/-]+\/$/).optional(),
};

/** Reviewed content states when its facts were checked and where they come from. */
function gate(entry: { reviewed: boolean; last_checked?: string; sources: unknown[] }, ctx: z.RefinementCtx) {
  if (!entry.reviewed) return;
  if (!entry.last_checked) ctx.addIssue({ code: "custom", path: ["last_checked"], message: "reviewed content needs last_checked" });
  if (entry.sources.length === 0) ctx.addIssue({ code: "custom", path: ["sources"], message: "reviewed content needs an official source" });
}

export const itinerarySchema = z.object({
  ...common,
  /** The destination city code (the contract's destinations[].code). One itinerary per city. */
  destination: cityCode,
  days: z.int().min(1).max(30),
}).superRefine(gate);

export const tipSchema = z.object({
  ...common,
  /** What the tip is about, e.g. "voos", "bagagem". */
  topic: z.string().regex(SLUG),
  /** City codes the tip is about, if any: those destination hubs list it (src/lib/related.ts). */
  destinations: z.array(cityCode).default([]),
}).superRefine(gate);

export type Itinerary = z.infer<typeof itinerarySchema>;
export type Tip = z.infer<typeof tipSchema>;
export type ContentKind = "itineraries" | "tips";

export interface BuildMode {
  /** `astro dev`: drafts are shown (with a notice) so Miguel can read them before approving. */
  dev: boolean;
  /** The site is built from fixture data (meta.fixture): test-only entries are included. */
  fixtureBuild: boolean;
}

/** Whether an entry is built and listed: reviewed (or the dev server), test-only on fixtures only. */
export function isVisible(entry: { reviewed: boolean; fixture: boolean }, mode: BuildMode): boolean {
  if (entry.fixture && !mode.fixtureBuild) return false;
  return entry.reviewed || mode.dev;
}

const SECTIONS: Record<ContentKind, string> = { itineraries: "roteiros", tips: "dicas" };

/** The page of an entry: the file name is the slug, chosen by hand ("paris-em-3-dias"). */
export function contentPath(kind: ContentKind, id: string): string {
  if (!SLUG.test(id)) throw new Error(`${kind}/${id}: the file name must be a slug (a-z, 0-9, hyphens)`);
  return `/${SECTIONS[kind]}/${id}/`;
}

/** Listing order: most recently checked first, then by title (pt collation). */
export function byLastChecked<T extends { data: { last_checked?: string; title: string } }>(a: T, b: T): number {
  return (b.data.last_checked ?? "").localeCompare(a.data.last_checked ?? "")
    || a.data.title.localeCompare(b.data.title, "pt");
}

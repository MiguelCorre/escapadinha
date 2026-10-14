// Content collections (#17, D33): itineraries and tips as MDX, front matter checked by the schemas
// in src/lib/content.ts. Each collection reads the hand-written files in src/content/<kind>/ and
// the test-only ones in test/fixtures/content/<kind>/ (front matter `fixture: true`); which entries
// are built is the review gate's job (src/collections.ts), not the loader's, so every file,
// drafts included, is validated on every build. The file name is the slug.
import { defineCollection } from "astro:content";
import { glob } from "astro/loaders";
import { itinerarySchema, tipSchema, type ContentKind } from "./lib/content";

const files = (kind: ContentKind) => glob({
  base: ".",
  pattern: [`src/content/${kind}/*.mdx`, `test/fixtures/content/${kind}/*.mdx`],
  generateId: ({ entry }) => entry.split("/").pop()!.replace(/\.mdx$/, ""),
});

export const collections = {
  itineraries: defineCollection({ loader: files("itineraries"), schema: itinerarySchema }),
  tips: defineCollection({ loader: files("tips"), schema: tipSchema }),
};

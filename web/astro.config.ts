import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import mdx from "@astrojs/mdx";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, fontProviders } from "astro/config";
import { siteDataPlugin } from "./src/lib/site-data-plugin";
import { sitemap } from "./src/lib/sitemap";

// Static site from the website data contract (D27, D28). The data directory comes from
// SITE_DATA_DIR (relative to web/), default web/src/data; `npm run build:fixtures` points it at
// contract/site/v1/fixtures. The data is validated against the schemas before any page renders.

const tokens = JSON.parse(readFileSync(new URL("../docs/design/tokens.json", import.meta.url), "utf8"));

// The self-hosted OFL fonts shared with the slides (assets/fonts/, D22), served through Astro's
// Fonts API so it adds metric-matched fallbacks (size-adjust). font-display: optional (D28): the
// web font is used only when it arrives before first paint (from cache after the first page), so
// it never moves the layout. Family names and fallback stacks come from tokens.json; the Tailwind theme
// (src/styles/tokens.css) points font-display / font-text at these variables.
const FONT_FILES: Record<string, { normal: string; italic: string; weight: string }> = {
  display: { normal: "Fraunces-Roman.woff2", italic: "Fraunces-Italic.woff2", weight: "100 900" },
  text: { normal: "SourceSerif4-Roman.woff2", italic: "SourceSerif4-Italic.woff2", weight: "200 900" },
};
const fonts = Object.entries(FONT_FILES).map(([role, files]) => {
  const [name, ...fallbacks] = tokens.fontFamily[role] as string[];
  return {
    provider: fontProviders.local(),
    name,
    cssVariable: `--pn-font-${role}` as const,
    fallbacks,
    options: {
      variants: (["normal", "italic"] as const).map((style) => ({
        src: [`../assets/fonts/${files[style]}`] as [string],
        weight: files.weight,
        style,
        display: "optional" as const,
      })) as [any, ...any[]],
    },
  };
});

export default defineConfig({
  output: "static",
  outDir: "./dist",
  trailingSlash: "always",
  build: { format: "directory", inlineStylesheets: "always" },
  fonts,
  // Itineraries and tips (src/content.config.ts, D33); sitemap.xml from the built pages (D34).
  integrations: [mdx(), sitemap()],
  vite: {
    plugins: [tailwindcss(), siteDataPlugin()],
    // Fonts and logos live in the repository's assets/ (shared with the slides).
    server: { fs: { allow: [fileURLToPath(new URL("..", import.meta.url))] } },
  },
});

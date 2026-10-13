// Generate src/styles/tokens.css (Tailwind v4 @theme + --pn-* palette variables) from the design
// system's machine-readable tokens, docs/design/tokens.json (itself generated from
// src/escapadinha/renderer/tokens.py). Run `npm run tokens` after the tokens change; a vitest test
// and tests/test_web_tokens.py fail while the CSS is stale.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const SOURCE = resolve(WEB_DIR, "../docs/design/tokens.json");
export const OUT = resolve(WEB_DIR, "src/styles/tokens.css");

const kebab = (s) => s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

function palette(theme, indent) {
  return Object.entries(theme).map(([name, value]) => `${indent}--pn-${name}: ${value};`).join("\n");
}

/** tokens.json -> the CSS text of src/styles/tokens.css (deterministic). */
export function renderTokensCss(tokens) {
  const theme = [];
  theme.push("  --color-*: initial;");
  for (const [name, value] of Object.entries(tokens.colors)) theme.push(`  --color-${name}: ${value};`);
  theme.push("  --font-*: initial;");
  // The stacks themselves (family + fallbacks from tokens.json, plus metric-matched fallbacks) are
  // emitted by Astro's Fonts API as --pn-font-<role> (astro.config.ts).
  for (const name of Object.keys(tokens.fontFamily)) theme.push(`  --font-${name}: var(--pn-font-${name});`);
  theme.push("  --text-*: initial;");
  for (const [name, [size, opts]] of Object.entries(tokens.fontSize)) {
    theme.push(`  --text-${name}: ${size};`);
    for (const [key, value] of Object.entries(opts)) theme.push(`  --text-${name}--${kebab(key)}: ${value};`);
  }
  theme.push("  --spacing: 0.25rem;");
  for (const [name, value] of Object.entries(tokens.spacing)) theme.push(`  --spacing-${name}: ${value};`);
  theme.push("  --radius-*: initial;");
  for (const [name, value] of Object.entries(tokens.borderRadius)) theme.push(`  --radius-${name}: ${value};`);
  theme.push("  --shadow-*: initial;");
  for (const [name, value] of Object.entries(tokens.boxShadow)) theme.push(`  --shadow-${name}: ${value};`);
  theme.push("  --container-page: 70rem;", "  --container-measure: 68ch;");

  const photo = Object.entries(tokens.photo).map(([k, v]) => `  --pn-photo-${kebab(k)}: ${v};`).join("\n");
  return [
    "/* Generated from docs/design/tokens.json by web/scripts/tokens.mjs (`npm run tokens`).",
    "   Do not edit by hand. Tailwind classes point at the --pn-* variables, so one class works in",
    "   both colour schemes; the theme namespaces are reset so no Tailwind default leaks through. */",
    "@theme {",
    ...theme,
    "}",
    "",
    ":root {",
    palette(tokens.themes.light, "  "),
    photo,
    "}",
    "",
    "@media (prefers-color-scheme: dark) {",
    "  :root:not([data-theme=\"light\"]) {",
    palette(tokens.themes.dark, "    "),
    "  }",
    "}",
    "",
    ":root[data-theme=\"dark\"] {",
    palette(tokens.themes.dark, "  "),
    "}",
    "",
  ].join("\n");
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  writeFileSync(OUT, renderTokensCss(JSON.parse(readFileSync(SOURCE, "utf8"))));
  console.log(`wrote ${OUT}`);
}

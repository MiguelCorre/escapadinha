// Styles use only the generated tokens (CLAUDE.md, D28): no raw colour in the templates, the
// stylesheet or the modules that draw (the OG image, the review Function's page). Colours come
// from Tailwind classes, the --pn-* variables (src/styles/tokens.css) or TOKENS
// (src/lib/tokens.ts); both generated files are the only place a hex value may live.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const GENERATED = new Set(["src/styles/tokens.css", "src/lib/tokens.ts"]);

/** "#1E1B16", "#fff", "#1E1B16CC" (not an HTML entity like "&#39;"), or rgb()/hsl() literals. */
const RAW_COLOUR = /(?<![&\w])#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})(?![\w-])|\b(?:rgba?|hsla?)\(\s*\d/gi;

function files(dir: string, ext: RegExp): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((e) => e.isFile() && ext.test(e.name))
    .map((e) => relative(WEB, join(e.parentPath, e.name)).replace(/\\/g, "/"));
}

export function rawColours(source: string): string[] {
  return [...source.matchAll(RAW_COLOUR)].map((m) => m[0]);
}

const SCANNED = [
  ...files(resolve(WEB, "src"), /\.(astro|ts|css)$/),
  ...files(resolve(WEB, "functions"), /\.ts$/),
].filter((f) => !GENERATED.has(f)).sort();

describe("no raw colours outside the generated tokens", () => {
  it("scans the templates, the global stylesheet and the review Function", () => {
    expect(SCANNED).toContain("src/styles/global.css");
    expect(SCANNED).toContain("src/components/PromotionCard.astro");
    expect(SCANNED).toContain("functions/_lib/review/page.ts");
  });

  it.each(SCANNED)("%s", (file) => {
    expect(rawColours(readFileSync(resolve(WEB, file), "utf8"))).toEqual([]);
  });

  it("the guard catches hex in Tailwind arbitrary values and CSS, not entities or ids", () => {
    expect(rawColours('class="from-[#3D372C] to-[#16140F]"')).toEqual(["#3D372C", "#16140F"]);
    expect(rawColours("a { color: #fff; background: rgba(0, 0, 0, .5) }")).toEqual(["#fff", "rgba(0"]);
    expect(rawColours('"&#39;" href="#fila" href="#decisoes" id="deal-12" #12')).toEqual([]);
  });
});

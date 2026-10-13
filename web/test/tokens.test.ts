// The design-system tokens reach Tailwind through src/styles/tokens.css, generated from
// docs/design/tokens.json by `npm run tokens` (never edited by hand).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { OUT, SOURCE, renderTokensCss } from "../scripts/tokens.mjs";

// Git may check the file out with CRLF (core.autocrlf); compare the content, not the line ends.
const committed = readFileSync(OUT, "utf8").replace(/\r\n/g, "\n");

describe("design tokens", () => {
  it("are up to date with docs/design/tokens.json (run `npm run tokens`)", () => {
    expect(committed).toBe(renderTokensCss(JSON.parse(readFileSync(SOURCE, "utf8"))));
  });

  it("carry the light and dark palettes as --pn-* variables", () => {
    expect(committed).toMatch(/:root \{[^}]*--pn-bg: #F5F0E6;/);
    expect(committed).toMatch(/prefers-color-scheme: dark\)[\s\S]*--pn-bg: #16140F;/);
    expect(committed).toMatch(/:root\[data-theme="dark"\] \{[^}]*--pn-accent: #F0936B;/);
  });

  it("replace Tailwind's default colours, fonts, sizes, radii and shadows", () => {
    for (const ns of ["color", "font", "text", "radius", "shadow"]) {
      expect(committed).toContain(`--${ns}-*: initial;`);
    }
    expect(committed).toContain("--color-accent: var(--pn-accent);");
    expect(committed).toContain("--text-price-xl: 4rem;");
    expect(committed).toContain("--text-label--letter-spacing: 0.14em;");
    expect(committed).toContain("--spacing-lg: 1.5rem;");
  });
});

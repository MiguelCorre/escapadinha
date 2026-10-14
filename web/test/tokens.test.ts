// The design-system tokens reach Tailwind through src/styles/tokens.css and code through
// src/lib/tokens.ts, both generated from docs/design/tokens.json by `npm run tokens` (never
// edited by hand).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { OUT, OUT_TS, SOURCE, renderTokensCss, renderTokensTs } from "../scripts/tokens.mjs";
import { TOKENS } from "../src/lib/tokens";

// Git may check the file out with CRLF (core.autocrlf); compare the content, not the line ends.
const read = (path: string) => readFileSync(path, "utf8").replace(/\r\n/g, "\n");
const committed = read(OUT);
const source = JSON.parse(readFileSync(SOURCE, "utf8"));

describe("design tokens", () => {
  it("are up to date with docs/design/tokens.json (run `npm run tokens`)", () => {
    expect(committed).toBe(renderTokensCss(source));
    expect(read(OUT_TS)).toBe(renderTokensTs(source));
  });

  it("are the same data in code as in tokens.json", () => {
    const { ["$schema-note"]: _note, ...data } = source;
    expect(TOKENS).toEqual(data);
  });

  it("carry the light and dark palettes as --pn-* variables", () => {
    expect(committed).toMatch(/:root \{[^}]*--pn-bg: #F5F0E6;/);
    expect(committed).toMatch(/prefers-color-scheme: dark\)[\s\S]*--pn-bg: #16140F;/);
    expect(committed).toMatch(/:root\[data-theme="dark"\] \{[^}]*--pn-accent: #F0936B;/);
    // The dark palette under fixed names, for surfaces that stay dark (photo placeholders).
    expect(committed).toMatch(/:root \{[^}]*--pn-dark-rule: #3D372C;/);
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

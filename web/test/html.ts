// Helpers to read the site built by build-site.ts.
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { inject } from "vitest";
import { parse, type HTMLElement } from "node-html-parser";

export function distDir(): string {
  return inject("distDir");
}

/** Site paths ("/", "/promos/3-lisboa-paris/") of every built HTML page. */
export function builtPages(): string[] {
  const dir = distDir();
  const walk = (d: string): string[] =>
    readdirSync(d, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? walk(join(d, e.name)) : e.name.endsWith(".html") ? [join(d, e.name)] : []);
  return walk(dir).map((file) => {
    const rel = "/" + relative(dir, file).split(sep).join("/");
    return rel.endsWith("/index.html") ? rel.slice(0, -"index.html".length) : rel;
  });
}

export function pageSource(path: string): string {
  const file = path.endsWith("/") ? `${path}index.html` : path;
  return readFileSync(join(distDir(), ...file.split("/").filter(Boolean)), "utf8");
}

export function page(path: string): HTMLElement {
  return parse(pageSource(path), { comment: false });
}

/** Visible text with whitespace collapsed (no-break spaces kept). */
export function text(el: HTMLElement): string {
  return el.textContent.replace(/[ \t\r\n]+/g, " ").trim();
}

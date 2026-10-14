// Helpers to read the site built by build-site.ts.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { inject } from "vitest";
import { parse, type HTMLElement } from "node-html-parser";

export function distDir(): string {
  return inject("distDir");
}

/** Site paths ("/", "/promos/3-lisboa-paris/") of every built HTML page. */
export function builtPages(): string[] {
  return builtPagesIn(distDir());
}

/** Site paths of every HTML page built into `dir`. */
export function builtPagesIn(dir: string): string[] {
  const walk = (d: string): string[] =>
    readdirSync(d, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? walk(join(d, e.name)) : e.name.endsWith(".html") ? [join(d, e.name)] : []);
  return walk(dir).map((file) => {
    const rel = "/" + relative(dir, file).split(sep).join("/");
    return rel.endsWith("/index.html") ? rel.slice(0, -"index.html".length) : rel;
  });
}

export function pageSource(path: string, dir = distDir()): string {
  const file = path.endsWith("/") ? `${path}index.html` : path;
  return readFileSync(join(dir, ...file.split("/").filter(Boolean)), "utf8");
}

/** Internal links (a/link href, img src starting with "/") on the pages built into `dir` whose
 * target is not a built page or file: "<page> -> <target>". */
export function brokenLinks(dir: string): string[] {
  const broken: string[] = [];
  for (const path of builtPagesIn(dir)) {
    const doc = parse(pageSource(path, dir), { comment: false });
    for (const a of doc.querySelectorAll("a[href^='/'], link[href^='/'], img[src^='/']")) {
      const target = (a.getAttribute("href") ?? a.getAttribute("src"))!.split("#")[0];
      const file = target.endsWith("/") ? join(target, "index.html") : target;
      if (!existsSync(join(dir, file))) broken.push(`${path} -> ${target}`);
    }
  }
  return broken;
}

export function page(path: string): HTMLElement {
  return parse(pageSource(path), { comment: false });
}

/** Visible text with whitespace collapsed (no-break spaces kept). */
export function text(el: HTMLElement): string {
  return el.textContent.replace(/[ \t\r\n]+/g, " ").trim();
}

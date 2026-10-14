// sitemap.xml (D34), written once the build is done, from the built pages themselves: every HTML
// page with a canonical URL and without <meta name="robots" content="noindex">. So the sitemap
// can't disagree with the pages: expired promotions, empty or past pontes, empty listings, drafts
// and the 404 page decide their own noindex (D28, D31, D33) and are left out by that alone.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { AstroIntegration } from "astro";

export interface PageSeo {
  canonical: string | null;
  noindex: boolean;
}

const attr = (tag: string, name: string) =>
  new RegExp(`\\s${name}\\s*=\\s*"([^"]*)"`, "i").exec(tag)?.[1] ?? null;

/** Canonical URL and robots noindex of one built page, from its <head>. */
export function pageSeo(html: string): PageSeo {
  const head = html.slice(0, Math.max(0, html.indexOf("</head>")) || html.length);
  let canonical: string | null = null;
  let noindex = false;
  for (const tag of head.match(/<(link|meta)\b[^>]*>/gi) ?? []) {
    if (/^<link/i.test(tag) && attr(tag, "rel")?.toLowerCase() === "canonical") canonical = attr(tag, "href");
    if (/^<meta/i.test(tag) && attr(tag, "name")?.toLowerCase() === "robots"
      && /\bnoindex\b/i.test(attr(tag, "content") ?? "")) noindex = true;
  }
  return { canonical, noindex };
}

const xmlEscape = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");

/** The sitemap of the indexable pages, sorted. */
export function sitemapXml(pages: PageSeo[]): string {
  const urls = [...new Set(pages.filter((p) => p.canonical && !p.noindex).map((p) => p.canonical!))].sort();
  return '<?xml version="1.0" encoding="UTF-8"?>\n'
    + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    + urls.map((u) => `  <url><loc>${xmlEscape(u)}</loc></url>\n`).join("")
    + "</urlset>\n";
}

function htmlFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? htmlFiles(join(dir, e.name)) : e.name.endsWith(".html") ? [join(dir, e.name)] : []);
}

/** Astro integration: writes <outDir>/sitemap.xml after every build. */
export function sitemap(): AstroIntegration {
  return {
    name: "pontonomada:sitemap",
    hooks: {
      "astro:build:done": ({ dir, logger }) => {
        const out = fileURLToPath(dir);
        const pages = htmlFiles(out).map((f) => pageSeo(readFileSync(f, "utf8")));
        const xml = sitemapXml(pages);
        writeFileSync(join(out, "sitemap.xml"), xml);
        logger.info(`sitemap.xml: ${(xml.match(/<loc>/g) ?? []).length} of ${pages.length} pages`);
      },
    },
  };
}

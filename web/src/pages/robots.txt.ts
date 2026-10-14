// robots.txt (D34): everything may be crawled (noindex pages say so themselves), and the sitemap
// on the contract's base URL. The sitemap itself is written after the build (src/lib/sitemap.ts).
import type { APIRoute } from "astro";
import data from "virtual:site-data";

export const GET: APIRoute = () =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${data.meta.base_url}/sitemap.xml\n`, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });

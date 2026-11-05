// "há 2 h" next to "encontrado a 01/11/2026 às 13:05" (D59, #81): added in the visitor's browser
// from the element's data-found-at (the UTC instant the contract gives), with format.timeAgo's
// thresholds, because our promotions last hours. A few lines of our own: no third party, no
// cookie, no storage, no request (web/test/seo.test.ts checks this file for those). Without
// JavaScript the absolute Lisbon time stays; the build never writes a relative time, so a page
// is not "per run" for it. Browser-safe and pure over the DOM: the explorer's island calls it
// again for the rows it renders.
import { timeAgo } from "./format";

export const FOUND_AGO_ATTR = "data-found-ago";

/** Appends " (há x h)" to every [data-found-at] element under `root` not yet upgraded; returns
 * how many it upgraded. */
export function upgradeFoundAt(root: ParentNode, now: Date = new Date()): number {
  let upgraded = 0;
  for (const el of Array.from(root.querySelectorAll("[data-found-at]"))) {
    const utc = el.getAttribute("data-found-at");
    if (!utc || el.hasAttribute(FOUND_AGO_ATTR) || Number.isNaN(Date.parse(utc))) continue;
    el.setAttribute(FOUND_AGO_ATTR, "");
    el.textContent = `${el.textContent} (${timeAgo(utc, now)})`;
    upgraded += 1;
  }
  return upgraded;
}

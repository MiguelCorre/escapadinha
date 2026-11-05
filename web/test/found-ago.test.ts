// The found-ago upgrade (D59, #81): "(há x h)" appended in the browser to every element that
// carries data-found-at, once, with format.timeAgo's words; nothing without the attribute or
// with a value that is not an instant. Run over node-html-parser's DOM, as the explorer's tests do.
import { parse } from "node-html-parser";
import { describe, expect, it } from "vitest";
import { FOUND_AGO_ATTR, upgradeFoundAt } from "../src/lib/found-ago";

const NOW = new Date("2026-11-01T15:05:00Z");

describe("found-ago", () => {
  it("appends how long ago, once per element, and leaves the absolute time in place", () => {
    const doc = parse(`<main>
      <span data-found-at="2026-11-01T13:05:00Z">01/11/2026 às 13:05</span>
      <span data-found-at="2026-10-30T13:05:00Z">30/10/2026 às 13:05</span>
      <span>01/11/2026</span>
      <span data-found-at="">—</span>
      <span data-found-at="not a time">—</span>
    </main>`);
    expect(upgradeFoundAt(doc as unknown as ParentNode, NOW)).toBe(2);
    const spans = doc.querySelectorAll("span").map((s) => s.textContent.trim());
    expect(spans).toEqual(["01/11/2026 às 13:05 (há 2 h 00)", "30/10/2026 às 13:05 (há 2 dias)",
      "01/11/2026", "—", "—"]);
    expect(doc.querySelectorAll(`[${FOUND_AGO_ATTR}]`)).toHaveLength(2);
    expect(upgradeFoundAt(doc as unknown as ParentNode, NOW)).toBe(0);     // idempotent
    expect(doc.querySelector("span")!.textContent).toBe("01/11/2026 às 13:05 (há 2 h 00)");
  });
});

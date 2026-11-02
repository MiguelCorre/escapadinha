// One page per promotion (D53), on the configured build, where the live promotion has a second
// live date in its group (build-site.ts): the lead's page lists both dates, each price on its own
// observation with its own booking link; the member has no page or card of its own; a promotion
// of one live date (the fixture build's) has no dates list.
import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, inject, it } from "vitest";
import { parse } from "node-html-parser";
import { GROUP_MEMBER_ID, GROUP_MEMBER_LATEST_OBS, GROUP_MEMBER_LATEST_PRICE, GROUP_MEMBER_LINK } from "./build-site";
import { builtPagesIn, pageSource, text } from "./html";

const distDir = inject("configuredDistDir");
const doc = (path: string) => parse(pageSource(path, distDir), { comment: false });
const LEAD = "/promos/412-porto-milao/";
const promoPages = (dir: string) => builtPagesIn(dir).filter((p) => p.startsWith("/promos/"));

describe("a promotion with two live dates (D53)", () => {
  it("is one page: the member date has no page of its own", () => {
    const pages = builtPagesIn(distDir);
    expect(pages).toContain(LEAD);
    expect(promoPages(distDir)).toEqual(promoPages(inject("distDir")));          // no page more
    expect(existsSync(join(distDir, "promos", `${GROUP_MEMBER_ID}-porto-milao`))).toBe(false);
  });

  it("lists every live date, cheapest first, each price on its observation with its own link", () => {
    const d = doc(LEAD);
    const section = d.querySelector("main [data-dates]")!;
    expect(section).not.toBeNull();
    expect(text(section.querySelector("h2")!)).toBe("Datas em promoção");
    const rows = section.querySelectorAll("li[data-deal]");
    expect(rows.map((r) => r.getAttribute("data-deal"))).toEqual(["412", String(GROUP_MEMBER_ID)]);
    expect(text(rows[0].querySelector("[data-obs]")!)).toBe("58 €");
    expect(rows[0].querySelector("[data-obs]")!.getAttribute("data-obs")).toBe("71428");
    // The member rose a euro since detection: the page shows the latest verified price, on
    // the recheck's observation (D53), not the detected one.
    expect(text(rows[1].querySelector("[data-obs]")!)).toBe(`${GROUP_MEMBER_LATEST_PRICE} €`);
    expect(rows[1].querySelector("[data-obs]")!.getAttribute("data-obs")).toBe(String(GROUP_MEMBER_LATEST_OBS));
    expect(text(rows[0])).toContain("sex, 12 fev → seg, 15 fev · 3 noites");
    expect(text(rows[1])).toContain("sex, 19 fev → seg, 22 fev · 3 noites");
    expect(rows[1].querySelector("a")!.getAttribute("href")).toBe(GROUP_MEMBER_LINK);
    expect(rows[1].querySelector("a")!.getAttribute("rel")).toContain("sponsored");
    // The headline price is still the lead's (the cheapest), on its observation.
    expect(text(d.querySelector("main [data-summary] [data-obs]")!)).toBe("58 €");
  });

  it("has one card on the home page, saying how many dates it lists", () => {
    const home = doc("/");
    const cards = home.querySelectorAll("#promocoes article[data-deal]");
    expect(cards.map((c) => c.getAttribute("data-deal"))).toEqual(["412", "408"]);   // two live promotions
    expect(text(cards[0].querySelector("[data-dates]")!)).toBe("2 datas a este preço ou perto");
    expect(cards[0].querySelector(`a[href="${LEAD}"]`)).not.toBeNull();
  });
});

describe("a promotion of one live date", () => {
  it("has its page, without a dates list", () => {
    const plain = inject("distDir");
    expect(promoPages(plain)).toContain(LEAD);
    const d = parse(pageSource(LEAD, plain), { comment: false });
    expect(d.querySelector("main [data-dates]")).toBeNull();
    expect(d.querySelector("#promocoes [data-dates]")).toBeNull();
  });
});

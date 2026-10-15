// Affiliate blocks (#18, D37) on the fixture build. The test itinerary (paris-em-3-dias) lists
// esim, insurance and activities in its front matter and places the three blocks in its body.
// The fixtures connect eSIM (Yesim) and activities (Tiqets) with placeholder links and no
// insurance programme, like config.yaml today: that block renders nothing and the build warns.
// The configured build gives insurance a fake brand and link, so its block renders, and drops the
// activities link (configured, not created yet): that block renders nothing and warns.
import { describe, expect, inject, it } from "vitest";
import { parse } from "node-html-parser";
import { affiliateBlock } from "../src/lib/affiliates";
import { CTA_REL } from "../src/lib/cta";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { page, pageSource, text } from "./html";
import { FAKE_INSURANCE_BRAND, FAKE_INSURANCE_LINK } from "./build-site";

const ITINERARY = "/roteiros/paris-em-3-dias/";
const FIXTURE_LINK = "https://example.com/parceiro/roteiro-paris-em-3-dias";
const DATA = loadSiteData(FIXTURES_DIR);
const DISCLOSURE = DATA.labels.disclosure.affiliate!;

const blocks = (root: ReturnType<typeof page>) => root.querySelectorAll("[data-affiliate]");
const configuredPage = () => parse(pageSource(ITINERARY, inject("configuredDistDir")), { comment: false });

describe("affiliate blocks", () => {
  it("renders the configured programmes' blocks inside the article, with the tracked link", () => {
    expect(DISCLOSURE).toMatch(/^Publicidade: /);
    const article = page(ITINERARY).querySelector("article")!;
    expect(blocks(article).map((b) => b.getAttribute("data-affiliate"))).toEqual(["esim", "activities"]);
    for (const block of blocks(article)) {
      const links = block.querySelectorAll("a");
      expect(links).toHaveLength(1);
      expect(links[0].getAttribute("href")).toBe(FIXTURE_LINK);
      expect(links[0].getAttribute("rel")).toBe(CTA_REL);
      expect(links[0].getAttribute("target")).toBe("_blank");
      expect(text(block)).toContain(DISCLOSURE);
    }
    const [esim, activities] = blocks(article);
    expect(text(esim)).toContain("Yesim");
    expect(text(esim)).toContain("eSIM");
    expect(text(activities)).toContain("Tiqets");
  });

  it("places each block where the author put it in the body", () => {
    const html = page(ITINERARY).querySelector(".prose")!.innerHTML;
    const at = (s: string) => html.indexOf(s);
    // eSIM before day 1, activities inside day 2.
    expect(at('data-affiliate="esim"')).toBeGreaterThan(-1);
    expect(at('data-affiliate="esim"')).toBeLessThan(at(">Dia 1<"));
    expect(at(">Dia 2<")).toBeLessThan(at('data-affiliate="activities"'));
    expect(at('data-affiliate="activities"')).toBeLessThan(at(">Dia 3<"));
  });

  it("renders nothing for a programme that is not configured, and the build warns", () => {
    expect(page(ITINERARY).querySelector('[data-affiliate="insurance"]')).toBeNull();
    expect(inject("buildLog")).toMatch(/itineraries\/paris-em-3-dias: insurance block not shown: no programme configured/);
  });

  it("renders nothing for a configured programme whose link is not created yet, and the build warns", () => {
    expect(configuredPage().querySelector('[data-affiliate="activities"]')).toBeNull();
    expect(inject("configuredBuildLog")).toMatch(/itineraries\/paris-em-3-dias: activities block not shown: no tracked link yet/);
    expect(inject("buildLog")).not.toMatch(/paris-em-3-dias: activities block not shown/);
  });

  it("adds no block to articles without one", () => {
    expect(blocks(page("/dicas/dica-de-teste/"))).toHaveLength(0);
  });

  it("renders a programme once it is configured (a config change only)", () => {
    const configured = configuredPage();
    const insurance = configured.querySelector('[data-affiliate="insurance"]')!;
    expect(insurance.querySelector("a")!.getAttribute("href")).toBe(FAKE_INSURANCE_LINK);
    expect(text(insurance)).toContain(FAKE_INSURANCE_BRAND);
    expect(text(insurance)).toContain(DISCLOSURE);
    expect(blocks(configured.querySelector("article")!).map((b) => b.getAttribute("data-affiliate")))
      .toEqual(["esim", "insurance"]);
    expect(inject("configuredBuildLog")).not.toMatch(/paris-em-3-dias: insurance block not shown/);
  });
});

describe("an author's mistake stops the build", () => {
  const paris = { key: "itineraries/paris-em-3-dias", affiliates: ["esim"] };

  it("refuses a block whose programme the front matter does not list", () => {
    expect(() => affiliateBlock(DATA, paris, "activities"))
      .toThrow('itineraries/paris-em-3-dias: the activities block needs "activities" in the front matter\'s affiliates');
    expect("block" in affiliateBlock(DATA, paris, "esim")).toBe(true);
  });

  it("refuses a block outside an itinerary or a tip", () => {
    expect(() => affiliateBlock(DATA, undefined, "esim")).toThrow("only be placed in an itinerary or a tip");
  });

  it("refuses a link that is not https, and a block without its disclosure", () => {
    const links = [{ article: paris.key, programme: "esim" as const, url: "http://x.example/" }];
    expect(() => affiliateBlock({ ...DATA, affiliates: { ...DATA.affiliates, links } }, paris, "esim"))
      .toThrow("not https");
    const labels = { ...DATA.labels, disclosure: { site: "x", post: "y" } };
    expect(() => affiliateBlock({ ...DATA, labels }, paris, "esim")).toThrow("disclosure");
  });
});

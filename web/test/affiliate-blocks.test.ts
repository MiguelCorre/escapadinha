// Affiliate blocks (#18, D37) on the fixture build. The test itinerary (paris-em-3-dias) lists
// esim, insurance and activities in its front matter and places the three blocks in its body.
// The fixtures connect eSIM (Yesim) and activities (Tiqets) with placeholder links and no
// insurance programme, like config.yaml today: that block renders nothing and the build warns.
// The configured build gives insurance a fake brand and link, so its block renders too.
import { describe, expect, inject, it } from "vitest";
import { parse } from "node-html-parser";
import { affiliateBlock } from "../src/lib/affiliates";
import { FIXTURES_DIR, loadSiteData } from "../src/lib/site-data";
import { page, pageSource, text } from "./html";
import { FAKE_INSURANCE_BRAND, FAKE_INSURANCE_LINK } from "./build-site";

const ITINERARY = "/roteiros/paris-em-3-dias/";
const FIXTURE_LINK = "https://example.com/parceiro/roteiro-paris-em-3-dias";
const DISCLOSURE = "Publicidade: esta ligação é um link de afiliado. Se comprares através dela, "
  + "podemos receber uma comissão, sem custo extra para ti.";

const blocks = (root: ReturnType<typeof page>) => root.querySelectorAll("[data-affiliate]");

describe("affiliate blocks", () => {
  it("renders the configured programmes' blocks inside the article, with the tracked link", () => {
    const article = page(ITINERARY).querySelector("article")!;
    expect(blocks(article).map((b) => b.getAttribute("data-affiliate"))).toEqual(["esim", "activities"]);
    for (const block of blocks(article)) {
      const links = block.querySelectorAll("a");
      expect(links).toHaveLength(1);
      expect(links[0].getAttribute("href")).toBe(FIXTURE_LINK);
      expect(links[0].getAttribute("rel")).toBe("sponsored nofollow noopener");
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

  it("adds no block to articles without one", () => {
    expect(blocks(page("/dicas/dica-de-teste/"))).toHaveLength(0);
  });

  it("renders a programme once it is configured (a config change only)", () => {
    const configured = parse(pageSource(ITINERARY, inject("configuredDistDir")), { comment: false });
    const insurance = configured.querySelector('[data-affiliate="insurance"]')!;
    expect(insurance.querySelector("a")!.getAttribute("href")).toBe(FAKE_INSURANCE_LINK);
    expect(text(insurance)).toContain(FAKE_INSURANCE_BRAND);
    expect(text(insurance)).toContain(DISCLOSURE);
    expect(blocks(configured.querySelector("article")!).map((b) => b.getAttribute("data-affiliate")))
      .toEqual(["esim", "activities", "insurance"]);
  });
});

describe("an author's mistake stops the build", () => {
  const data = loadSiteData(FIXTURES_DIR).affiliates;
  const paris = { key: "itineraries/paris-em-3-dias", affiliates: ["esim"] };

  it("refuses a block whose programme the front matter does not list", () => {
    expect(() => affiliateBlock(data, paris, "activities"))
      .toThrow('itineraries/paris-em-3-dias: the activities block needs "activities" in the front matter\'s affiliates');
    expect("block" in affiliateBlock(data, paris, "esim")).toBe(true);
  });

  it("refuses a block outside an itinerary or a tip", () => {
    expect(() => affiliateBlock(data, undefined, "esim")).toThrow("only be placed in an itinerary or a tip");
  });

  it("refuses a link that is not https", () => {
    const http = { ...data, links: [{ article: paris.key, programme: "esim" as const, url: "http://x.example/" }] };
    expect(() => affiliateBlock(http, paris, "esim")).toThrow("not https");
  });
});

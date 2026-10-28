// vitest globalSetup: build the site once from the committed fixtures (contract/site/v1/fixtures)
// into a temporary folder; the HTML tests read it through inject("distDir"). Then, one after the
// other (two astro builds of one project must not run at once: they share .astro/), the same
// fixtures with the third-party settings filled in with fake values (D34: analytics token and
// search widget) and the live promotion published on Instagram with a fake post URL (D36), read
// through inject("configuredDistDir"). The configured build also connects an insurance programme
// (fake brand and link, D37), so the block that renders nothing on the fixtures renders there, and
// drops the activities link (configured, link not created yet: nothing rendered, a warning). Both
// builds' output is kept for the tests of their warnings (inject("buildLog"), "configuredBuildLog").
import { spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { TestProject } from "vitest/node";

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FIXTURES = "../contract/site/v1/fixtures";

/** Clearly fake values for the configured build: never a real token or widget. */
export const FAKE_ANALYTICS_TOKEN = "fakeTestToken0000000000000000000";
export const FAKE_SEARCH_WIDGET = "https://tp.media/content?fake=test-only&promo_id=0";
/** The live promotion published on Instagram (D36): its post link on the page. */
export const FAKE_POST_URL = "https://www.instagram.com/p/fake-test-only/";
/** An insurance programme connected in the configured build (D37). */
export const FAKE_INSURANCE_BRAND = "Seguradora de Teste";
export const FAKE_INSURANCE_LINK = "https://example.com/parceiro/seguro-de-teste";
/** The second live date of the live promotion in the configured build (D53). */
export const GROUP_MEMBER_ID = 1008;
export const GROUP_MEMBER_OBS = 999001;
export const GROUP_MEMBER_PRICE = 71;
export const GROUP_MEMBER_LINK = "https://example.com/parceiro/site-deal-1008";

function build(dataDir: string, outDir: string): string {
  const result = spawnSync(
    process.execPath,
    // --force: Astro's content cache ignores front matter schema changes (D37).
    [join(WEB_DIR, "node_modules/astro/bin/astro.mjs"), "build", "--force", "--outDir", outDir],
    { cwd: WEB_DIR, encoding: "utf8", env: { ...process.env, SITE_DATA_DIR: dataDir, ASTRO_TELEMETRY_DISABLED: "1" } },
  );
  if (result.status !== 0) {
    throw new Error(`astro build failed:\n${result.stdout}\n${result.stderr}`);
  }
  return `${result.stdout}\n${result.stderr}`;
}

export default function setup(project: TestProject) {
  const distDir = mkdtempSync(join(tmpdir(), "pn-web-dist-"));
  project.provide("buildLog", build(FIXTURES, distDir));
  project.provide("distDir", distDir);

  const configuredData = mkdtempSync(join(tmpdir(), "pn-configured-data-"));
  const configuredDist = mkdtempSync(join(tmpdir(), "pn-configured-dist-"));
  cpSync(resolve(WEB_DIR, FIXTURES), configuredData, { recursive: true });
  const meta = JSON.parse(readFileSync(join(configuredData, "meta.json"), "utf8"));
  writeFileSync(join(configuredData, "meta.json"), JSON.stringify({
    ...meta, analytics_token: FAKE_ANALYTICS_TOKEN, search_widget: FAKE_SEARCH_WIDGET,
  }));
  const promotions = JSON.parse(readFileSync(join(configuredData, "promotions.json"), "utf8"));
  for (const p of promotions.promotions) {
    if (p.live) Object.assign(p, { status: "published", post_url: FAKE_POST_URL });
  }
  // D53: the live promotion gets a second live date (a dearer trip a week later) in the same
  // group: one page, two dates, the member's own old URL is no page.
  const lead = promotions.promotions.find((p: any) => p.live);
  const member = JSON.parse(JSON.stringify(lead));
  Object.assign(member, { id: GROUP_MEMBER_ID, status: "approved", post_url: null, images: null,
    booking_link: GROUP_MEMBER_LINK, also_seen: [] });
  Object.assign(member.offer, { obs: GROUP_MEMBER_OBS, price: GROUP_MEMBER_PRICE,
    departure: "2026-11-07", return: "2026-11-10", found_date: "2026-10-12" });
  const group = { id: 1, path: lead.path, lead: false, dates: [lead.id, member.id] };
  lead.promotion = { ...group, lead: true };
  member.promotion = { ...group };
  promotions.promotions.push(member);
  writeFileSync(join(configuredData, "promotions.json"), JSON.stringify(promotions));
  const affiliates = JSON.parse(readFileSync(join(configuredData, "affiliates.json"), "utf8"));
  affiliates.programmes.insurance = { brand: FAKE_INSURANCE_BRAND };
  affiliates.links = affiliates.links.filter((l: { programme: string }) => l.programme !== "activities");
  affiliates.links.push({ article: "itineraries/paris-em-3-dias", programme: "insurance", url: FAKE_INSURANCE_LINK });
  writeFileSync(join(configuredData, "affiliates.json"), JSON.stringify(affiliates));
  project.provide("configuredBuildLog", build(configuredData, configuredDist));
  project.provide("configuredDistDir", configuredDist);

  return () => {
    for (const dir of [distDir, configuredData, configuredDist]) rmSync(dir, { recursive: true, force: true });
  };
}

declare module "vitest" {
  export interface ProvidedContext {
    distDir: string;
    configuredDistDir: string;
    buildLog: string;
    configuredBuildLog: string;
  }
}

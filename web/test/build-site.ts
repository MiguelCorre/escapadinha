// vitest globalSetup: build the site once from the committed fixtures (contract/site/v1/fixtures)
// into a temporary folder; the HTML tests read it through inject("distDir"). Then, one after the
// other (two astro builds of one project must not run at once: they share .astro/), the same
// fixtures with the third-party settings filled in with fake values (D34: analytics token and
// search widget) and the live promotion published on Instagram with a fake post URL (D36), read
// through inject("configuredDistDir").
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

function build(dataDir: string, outDir: string) {
  const result = spawnSync(
    process.execPath,
    [join(WEB_DIR, "node_modules/astro/bin/astro.mjs"), "build", "--outDir", outDir],
    { cwd: WEB_DIR, encoding: "utf8", env: { ...process.env, SITE_DATA_DIR: dataDir, ASTRO_TELEMETRY_DISABLED: "1" } },
  );
  if (result.status !== 0) {
    throw new Error(`astro build failed:\n${result.stdout}\n${result.stderr}`);
  }
}

export default function setup(project: TestProject) {
  const distDir = mkdtempSync(join(tmpdir(), "pn-web-dist-"));
  build(FIXTURES, distDir);
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
  writeFileSync(join(configuredData, "promotions.json"), JSON.stringify(promotions));
  build(configuredData, configuredDist);
  project.provide("configuredDistDir", configuredDist);

  return () => {
    for (const dir of [distDir, configuredData, configuredDist]) rmSync(dir, { recursive: true, force: true });
  };
}

declare module "vitest" {
  export interface ProvidedContext {
    distDir: string;
    configuredDistDir: string;
  }
}

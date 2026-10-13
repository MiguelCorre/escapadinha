// vitest globalSetup: build the site once from the committed fixtures (contract/site/v1/fixtures)
// into a temporary folder; the HTML tests read it through inject("distDir").
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { TestProject } from "vitest/node";

const WEB_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");

export default function setup(project: TestProject) {
  const distDir = mkdtempSync(join(tmpdir(), "pn-web-dist-"));
  const result = spawnSync(
    process.execPath,
    [join(WEB_DIR, "node_modules/astro/bin/astro.mjs"), "build", "--outDir", distDir],
    {
      cwd: WEB_DIR,
      encoding: "utf8",
      env: { ...process.env, SITE_DATA_DIR: "../contract/site/v1/fixtures", ASTRO_TELEMETRY_DISABLED: "1" },
    },
  );
  if (result.status !== 0) {
    throw new Error(`astro build failed:\n${result.stdout}\n${result.stderr}`);
  }
  project.provide("distDir", distDir);
  return () => rmSync(distDir, { recursive: true, force: true });
}

declare module "vitest" {
  export interface ProvidedContext {
    distDir: string;
  }
}

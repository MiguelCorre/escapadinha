// Run a command with SITE_DATA_DIR pointing at the committed fixtures (contract/site/v1/fixtures),
// cross-platform: `node scripts/with-fixtures.mjs astro build`. A site built this way is test
// data (meta.fixture: true, <html data-fixture="true">): never deploy it.
import { spawnSync } from "node:child_process";

const [cmd, ...args] = process.argv.slice(2);
const result = spawnSync(cmd, args, {
  stdio: "inherit",
  shell: process.platform === "win32",
  env: { ...process.env, SITE_DATA_DIR: "../contract/site/v1/fixtures" },
});
process.exit(result.status ?? 1);

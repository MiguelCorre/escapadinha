// The Pages Functions routes (D29): /review and /review/* reach the handler; nothing else in
// web/functions/ is a route; the sources bundle without node_modules (wrangler builds them on
// the pipeline's runner, which never runs npm ci).
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as catchAll from "../../functions/review/[[path]]";
import * as index from "../../functions/review/index";
import { world } from "./helpers";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const FUNCTIONS = join(WEB, "functions");

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : e.name.endsWith(".ts") ? [join(dir, e.name)] : []);
}

const rel = (f: string) => relative(FUNCTIONS, f).split("\\").join("/");

describe("Pages Functions routes", () => {
  it("send /review and /review/* to the handler, which refuses requests without Access", async () => {
    const w = await world();
    for (const route of [index, catchAll]) {
      const res = await route.onRequest({ request: new Request("https://ondestaanocas.pages.dev/review"), env: w.env });
      expect(res.status).toBe(403);
    }
  });

  it("are the only files exporting onRequest handlers", () => {
    const routes = files(FUNCTIONS).filter((f) => /export\s+(const|function|async function)\s+onRequest/.test(readFileSync(f, "utf8")));
    expect(routes.map(rel).sort()).toEqual(["review/[[path]].ts", "review/index.ts"]);
  });

  it("import only relative modules inside web/functions or web/src/lib (no npm packages)", () => {
    for (const f of files(FUNCTIONS)) {
      for (const m of readFileSync(f, "utf8").matchAll(/^\s*(?:import|export)\b[^"']*?from\s+["']([^"']+)["']/gm)) {
        const spec = m[1];
        expect(spec.startsWith("."), `${rel(f)} imports ${spec}`).toBe(true);
        const target = relative(WEB, resolve(dirname(f), spec)).split("\\").join("/");
        expect(target.startsWith("functions/") || target.startsWith("src/lib/"), `${rel(f)} imports ${target}`).toBe(true);
      }
    }
  });
});

// What the Pages Functions runtime calls (functions/review/index.ts and [[path]].ts): the real
// clock, fetch, UUIDs and a per-isolate cache of the Access keys around the pure handler.
// Deliberately not named onRequest here: an exported onRequest* would make this file a route.
import { KeyCache } from "./access";
import { handle } from "./handler";
import type { Deps, Env } from "./types";

const keys = new KeyCache();

export function runtimeDeps(): Deps {
  return {
    fetch: (input, init) => fetch(input, init),   // an unbound global fetch throws in Workers
    now: () => new Date(),
    uuid: () => crypto.randomUUID(),
    keys,
  };
}

export function serve(context: { request: Request; env: Env }): Promise<Response> {
  return handle(context.request, context.env, runtimeDeps());
}

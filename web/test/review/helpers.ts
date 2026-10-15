// Test doubles for the review Function (#9, D29): an in-memory R2 bucket, a Cloudflare Access
// signer (an RSA key generated per test file, served as the team's certs), a fake fetch that
// records every outgoing call, and a schema-valid review snapshot (contract/review/v1).
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Ajv2020 } from "ajv/dist/2020.js";
import { KeyCache } from "../../functions/_lib/review/access";
import type { Bucket, Deps, Env } from "../../functions/_lib/review/types";

export const CONTRACT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../contract/review/v1");
export const TEAM = "pontonomada.cloudflareaccess.com";
export const AUD = "aud-tag-of-the-review-app";
export const EMAIL = "miguelahpc@hotmail.com";
export const NOW = new Date("2026-10-14T09:30:00Z");

// --- contract ------------------------------------------------------------------------------

const ajv = new Ajv2020({ allErrors: true, strict: false });
for (const name of ["event", "snapshot"]) {
  ajv.addSchema(JSON.parse(readFileSync(resolve(CONTRACT, `${name}.schema.json`), "utf8")));
}
const ID = "https://github.com/MiguelCorre/escapadinha/contract/review/v1/";

/** Schema errors of `data` against contract/review/v1/<name>.schema.json ([] when valid). */
export function schemaErrors(name: "event" | "snapshot", data: unknown): string[] {
  const validate = ajv.getSchema(`${ID}${name}.schema.json`)!;
  return validate(data) ? [] : (validate.errors ?? []).map((e) => `${e.instancePath} ${e.message}`);
}

// --- R2 bucket ---------------------------------------------------------------------------------

export class MemoryBucket implements Bucket {
  objects = new Map<string, Uint8Array>();
  failPuts = false;

  async get(key: string) {
    const data = this.objects.get(key);
    if (!data) return null;
    return {
      body: new Response(data.slice()).body!,
      text: async () => new TextDecoder().decode(data),
      arrayBuffer: async () => data.slice().buffer,
    };
  }

  async put(key: string, value: string | ArrayBuffer | Uint8Array) {
    if (this.failPuts) throw new Error("R2 indisponível");
    this.objects.set(key, typeof value === "string" ? new TextEncoder().encode(value) : new Uint8Array(value));
    return {};
  }

  async list(options: { prefix?: string; cursor?: string; limit?: number }) {
    const keys = [...this.objects.keys()].filter((k) => k.startsWith(options.prefix ?? "")).sort();
    const start = options.cursor ? Number(options.cursor) : 0;
    const limit = options.limit ?? 2; // tiny pages, so the Function must follow the cursor
    const page = keys.slice(start, start + limit);
    const truncated = start + limit < keys.length;
    return { objects: page.map((key) => ({ key })), truncated, cursor: truncated ? String(start + limit) : undefined };
  }

  putJson(key: string, value: unknown): void {
    this.objects.set(key, new TextEncoder().encode(JSON.stringify(value, null, 2)));
  }

  json(key: string): any {
    return JSON.parse(new TextDecoder().decode(this.objects.get(key)!));
  }

  keys(prefix = ""): string[] {
    return [...this.objects.keys()].filter((k) => k.startsWith(prefix)).sort();
  }
}

// --- Cloudflare Access -------------------------------------------------------------------------

const b64url = (data: Uint8Array | string) =>
  Buffer.from(typeof data === "string" ? new TextEncoder().encode(data) : data).toString("base64url");

export interface Signer {
  kid: string;
  jwks: { keys: JsonWebKey[] };
  sign(claims: Record<string, unknown>, header?: Record<string, unknown>): Promise<string>;
}

export async function accessSigner(kid = "test-key-1"): Promise<Signer> {
  const pair = (await crypto.subtle.generateKey(
    { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
    true, ["sign", "verify"])) as CryptoKeyPair;
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  return {
    kid,
    jwks: { keys: [{ kid, kty: jwk.kty, alg: "RS256", use: "sig", e: jwk.e, n: jwk.n } as JsonWebKey] },
    async sign(claims, header = {}) {
      const head = b64url(JSON.stringify({ alg: "RS256", kid, typ: "JWT", ...header }));
      const body = b64url(JSON.stringify(claims));
      const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", pair.privateKey, new TextEncoder().encode(`${head}.${body}`));
      return `${head}.${body}.${b64url(new Uint8Array(sig))}`;
    },
  };
}

/** Claims of a valid Access token for Miguel at NOW. */
export function claims(over: Record<string, unknown> = {}): Record<string, unknown> {
  const now = Math.floor(NOW.getTime() / 1000);
  return { aud: [AUD], email: EMAIL, iss: `https://${TEAM}`, iat: now - 60, nbf: now - 60,
    exp: now + 3600, sub: "user-id", type: "app", ...over };
}

// --- outgoing HTTP -----------------------------------------------------------------------------

export interface Call { url: string; method: string; headers: Headers; body: string | null }
type Route = (call: Call) => Response | Promise<Response>;

/** fetch double: routes by URL prefix, records every call. Unrouted calls fail the test. */
export class FakeNet {
  calls: Call[] = [];
  routes: [string, Route][] = [];

  on(prefix: string, route: Route): this {
    this.routes.unshift([prefix, route]);
    return this;
  }

  to(prefix: string): Call[] {
    return this.calls.filter((c) => c.url.startsWith(prefix));
  }

  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const req = new Request(input, init);
    const call = { url: req.url, method: req.method, headers: req.headers, body: req.body ? await req.text() : null };
    this.calls.push(call);
    const hit = this.routes.find(([prefix]) => call.url.startsWith(prefix));
    if (!hit) throw new Error(`unexpected fetch ${call.method} ${call.url}`);
    return hit[1](call);
  };
}

export const CERTS = `https://${TEAM}/cdn-cgi/access/certs`;
export const PRICES = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates";
export const DISPATCH = "https://api.github.com/repos/MiguelCorre/escapadinha/dispatches";

/** A Travelpayouts v3 item (the fields the pipeline reads). */
export function item(price: number, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    origin: "LIS", destination: "LON", origin_airport: "LIS", destination_airport: "LGW",
    price, airline: "TP", flight_number: "1336", transfers: 0, return_transfers: 0,
    departure_at: "2026-11-20T07:05:00+00:00", return_at: "2026-11-23T19:40:00+00:00",
    link: "/search/LIS2011LON23111?t=TP&search_date=14102026", ...over,
  };
}

export function pricesPayload(...items: Record<string, unknown>[]) {
  return { success: true, currency: "eur", data: items };
}

// --- snapshot ----------------------------------------------------------------------------------

export function deal(id: number, over: Record<string, any> = {}): Record<string, any> {
  return {
    id, status: "rendered", status_pt: "por rever", observation_id: 1000 + id, route: "LIS-LON",
    origin: "LIS", destination: "LON", origin_city: "Lisboa", destination_city: "Londres",
    headline: "Lisboa → Londres (Gatwick)", arrival_airport: "Gatwick", price_eur: 58, price: "58 €",
    departure_date: "2026-11-20", return_date: "2026-11-23", dates: "20 a 23 de novembro",
    nights: "3 noites", airline: "TAP Air Portugal", direct: true, transfers: 0, return_transfers: 0,
    rule: "median", discount_pct: 44,
    typical_low_eur: 104, baseline_days: 21, found_date: "2026-10-14", found_on: "14/10/2026",
    fetched_at: "2026-10-14T08:17:00Z", checked_at: "14/10/2026 às 09:17",
    detected_at: "2026-10-14T08:20:00Z", affiliate_url: `https://aviasales.tpo.lu/test-${id}`,
    affiliate_error: null, caption: "Lisboa → Londres por 58 €\n\nPublicidade: link de afiliado.",
    whatsapp_text: null, page_url: null,
    slides: [1, 2].map((n) => ({ url: null, key: `review/slides/${id}/slide_0${n}.webp` })),
    live_check: {
      last_checked_at: null, last_seen_price_eur: null, expired_reason: null,
      query: { origin: "LIS", destination: "LON", departure_at: "2026-11", one_way: "false",
        currency: "eur", sorting: "price", unique: "false", limit: 1000, direct: "true", market: "pt" },
      rules: { direct_only: true, max_transfers: 0, min_nights: 2, max_nights: 10, max_offer_age_days: 3 },
    },
    review_note: null, reviewed_at: null, published_at: null, post_url: null,
    ...over,
  };
}

export function snapshot(over: Record<string, any> = {}): Record<string, any> {
  return {
    version: 1, generated_at: "2026-10-14T08:21:00Z", site_base_url: "https://pontonomada.pt",
    review_rules: { approve_max_age_hours: 24 },
    queue: [deal(7), deal(6, { status: "new", status_pt: "novo", slides: [] })],
    approved: [deal(5, { status: "approved", status_pt: "aprovado", reviewed_at: "2026-10-13T20:00:00Z",
      page_url: "https://pontonomada.pt/promos/5-lisboa-londres/" })],
    published: [], closed: [], pending_events: [], recent_outcomes: [],
    ...over,
  };
}

// --- the Function's world ----------------------------------------------------------------------

export interface World { env: Env; deps: Deps; net: FakeNet; store: MemoryBucket; signer: Signer; token: string }

let ids = 0;

export async function world(snap: Record<string, any> | null = snapshot()): Promise<World> {
  const signer = await accessSigner();
  const store = new MemoryBucket();
  if (snap) store.putJson("review/snapshot.json", snap);
  const net = new FakeNet()
    .on(CERTS, () => Response.json({ keys: signer.jwks.keys }))
    .on(PRICES, () => Response.json(pricesPayload(item(58))))
    .on(DISPATCH, () => new Response(null, { status: 204 }));
  const env: Env = {
    ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, GITHUB_DISPATCH_TOKEN: "gh-test-token",
    TRAVELPAYOUTS_TOKEN: "tp-test-token", STORE: store,
  };
  const deps: Deps = {
    fetch: net.fetch, now: () => NOW,
    uuid: () => `00000000-0000-4000-8000-${String(++ids).padStart(12, "0")}`,
    keys: new KeyCache(),
  };
  return { env, deps, net, store, signer, token: await signer.sign(claims()) };
}

export function get(path: string, token?: string | null, headers: Record<string, string> = {}): Request {
  return new Request(`https://pontonomada.pt${path}`, {
    headers: { ...(token ? { "Cf-Access-Jwt-Assertion": token } : {}), ...headers },
  });
}

export function post(path: string, body: unknown, token?: string | null, headers: Record<string, string> = {}): Request {
  return new Request(`https://pontonomada.pt${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: "https://pontonomada.pt",
      ...(token ? { "Cf-Access-Jwt-Assertion": token } : {}), ...headers },
    body: JSON.stringify(body),
  });
}

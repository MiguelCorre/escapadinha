// Cloudflare Access JWT verification (D29). Access puts a signed token in the
// `Cf-Access-Jwt-Assertion` header of every request it lets through. The production pages.dev
// host is not behind Access (only a Bulk Redirect sends it to pontonomada.pt), so the Function
// must not trust the header's presence: it checks the RS256 signature against the team's
// published keys, the audience (the review application's AUD tag), the issuer and the validity
// window, and takes the reviewer's e-mail from the token. WebCrypto only.

export const HEADER = "Cf-Access-Jwt-Assertion";
const KEYS_TTL_MS = 60 * 60 * 1000;      // Access rotates its keys every 6 weeks, with overlap
const REFETCH_MS = 60 * 1000;            // unknown kid: fetch again, at most once a minute
const LEEWAY_S = 60;                     // clock skew allowed on nbf (iat is not checked)

export class AccessError extends Error {}

/** The team's public keys by `kid`, kept per isolate. */
export class KeyCache {
  keys = new Map<string, CryptoKey>();
  fetchedAt = -Infinity;
  domain = "";
}

export interface AccessConfig {
  teamDomain: string;
  aud: string;
}

type Fetch = typeof fetch;

/** Backed by a plain ArrayBuffer, which WebCrypto's BufferSource requires. */
function b64urlBytes(text: string): Uint8Array<ArrayBuffer> {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(text.length / 4) * 4, "=");
  const bin = atob(b64);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function b64urlJson(text: string): any {
  return JSON.parse(new TextDecoder().decode(b64urlBytes(text)));
}

/** "pontonomada.cloudflareaccess.com" (a pasted https:// or trailing slash is tolerated). */
export function teamHost(domain: string): string {
  return domain.trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

async function loadKeys(cache: KeyCache, host: string, fetchFn: Fetch, nowMs: number): Promise<void> {
  const res = await fetchFn(`https://${host}/cdn-cgi/access/certs`);
  if (!res.ok) throw new AccessError(`chaves do Access indisponíveis (HTTP ${res.status})`);
  const body = (await res.json()) as { keys?: (JsonWebKey & { kid?: string })[] };
  const keys = new Map<string, CryptoKey>();
  for (const jwk of body.keys ?? []) {
    if (!jwk.kid || jwk.kty !== "RSA") continue;
    keys.set(jwk.kid, await crypto.subtle.importKey(
      "jwk", { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]));
  }
  cache.keys = keys;
  cache.fetchedAt = nowMs;
  cache.domain = host;
}

async function keyFor(kid: string, cache: KeyCache, host: string, fetchFn: Fetch, nowMs: number): Promise<CryptoKey> {
  const stale = cache.domain !== host || nowMs - cache.fetchedAt > KEYS_TTL_MS;
  // A kid we don't know may be a rotation: fetch again, but not for every forged token.
  if (stale || (!cache.keys.has(kid) && nowMs - cache.fetchedAt > REFETCH_MS)) {
    await loadKeys(cache, host, fetchFn, nowMs);
  }
  const key = cache.keys.get(kid);
  if (!key) throw new AccessError("token assinado por uma chave desconhecida");
  return key;
}

/** The reviewer's e-mail from a valid Access token; AccessError (pt-PT reason) otherwise. */
export async function verifyAccess(token: string | null, config: AccessConfig,
  deps: { fetch: Fetch; now: () => Date; keys: KeyCache }): Promise<string> {
  const host = teamHost(config.teamDomain ?? "");
  if (!host || !config.aud) throw new AccessError("configuração do Access em falta");
  if (!token) throw new AccessError("sem token do Access");
  const parts = token.split(".");
  if (parts.length !== 3) throw new AccessError("token do Access inválido");
  let header: { alg?: string; kid?: string };
  let payload: Record<string, unknown>;
  try {
    header = b64urlJson(parts[0]);
    payload = b64urlJson(parts[1]);
  } catch {
    throw new AccessError("token do Access ilegível");
  }
  if (header.alg !== "RS256" || typeof header.kid !== "string") throw new AccessError("algoritmo do token não aceite");
  const nowMs = deps.now().getTime();
  const key = await keyFor(header.kid, deps.keys, host, deps.fetch, nowMs);
  const signed = new TextEncoder().encode(`${parts[0]}.${parts[1]}`);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64urlBytes(parts[2]), signed);
  if (!ok) throw new AccessError("assinatura do token inválida");

  const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!aud.includes(config.aud)) throw new AccessError("token de outra aplicação do Access");
  if (payload.iss !== `https://${host}`) throw new AccessError("token de outra equipa do Access");
  const now = nowMs / 1000;
  if (typeof payload.exp !== "number" || payload.exp <= now) throw new AccessError("token do Access expirado");
  if (typeof payload.nbf === "number" && payload.nbf > now + LEEWAY_S) throw new AccessError("token do Access ainda não é válido");
  if (typeof payload.email !== "string" || !payload.email.includes("@")) throw new AccessError("token sem e-mail");
  return payload.email;
}

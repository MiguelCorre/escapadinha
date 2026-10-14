// Every /review request must carry a valid Cloudflare Access token (#9, D29): the production
// pages.dev host is not behind Access, so the Function verifies the JWT itself.
import { describe, expect, it } from "vitest";
import { handle } from "../../functions/_lib/review/handler";
import { accessSigner, AUD, CERTS, claims, get, NOW, TEAM, world } from "./helpers";

describe("Access", () => {
  it("refuses a request without the Access assertion header, in pt-PT", async () => {
    const w = await world();
    const res = await handle(get("/review"), w.env, w.deps);
    expect(res.status).toBe(403);
    expect(await res.text()).toContain("Acesso negado");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it("serves the queue with a valid token", async () => {
    const w = await world();
    const res = await handle(get("/review", w.token), w.env, w.deps);
    expect(res.status).toBe(200);
  });

  it.each([
    ["another audience", { aud: ["someone-elses-app"] }],
    ["another issuer", { iss: "https://evil.cloudflareaccess.com" }],
    ["an expired token", { exp: Math.floor(NOW.getTime() / 1000) - 1 }],
    ["a token not valid yet", { nbf: Math.floor(NOW.getTime() / 1000) + 3600 }],
    ["no e-mail", { email: undefined }],
  ])("refuses %s", async (_, over) => {
    const w = await world();
    const token = await w.signer.sign(claims(over));
    const res = await handle(get("/review", token), w.env, w.deps);
    expect(res.status).toBe(403);
  });

  it("accepts the audience as a plain string too", async () => {
    const w = await world();
    const token = await w.signer.sign(claims({ aud: AUD }));
    expect((await handle(get("/review", token), w.env, w.deps)).status).toBe(200);
  });

  it("refuses a token signed by a key the team does not publish", async () => {
    const w = await world();
    const stranger = await accessSigner(w.signer.kid);       // same kid, other key
    const res = await handle(get("/review", await stranger.sign(claims())), w.env, w.deps);
    expect(res.status).toBe(403);
  });

  it("refuses a tampered payload and an unsigned (alg none) token", async () => {
    const w = await world();
    const [h, , s] = w.token.split(".");
    const forged = Buffer.from(JSON.stringify(claims({ email: "intruso@example.com" }))).toString("base64url");
    expect((await handle(get("/review", `${h}.${forged}.${s}`), w.env, w.deps)).status).toBe(403);
    const none = Buffer.from(JSON.stringify({ alg: "none", kid: w.signer.kid })).toString("base64url");
    expect((await handle(get("/review", `${none}.${forged}.`), w.env, w.deps)).status).toBe(403);
    expect((await handle(get("/review", "not-a-jwt"), w.env, w.deps)).status).toBe(403);
  });

  it("fails closed when the Access settings are missing", async () => {
    const w = await world();
    const res = await handle(get("/review", w.token), { ...w.env, ACCESS_AUD: "" }, w.deps);
    expect(res.status).toBe(403);
    expect(w.net.to(CERTS)).toHaveLength(0);
  });

  it("caches the team's keys and fetches them again for an unknown key id", async () => {
    const w = await world();
    await handle(get("/review", w.token), w.env, w.deps);
    await handle(get("/review", w.token), w.env, w.deps);
    expect(w.net.to(CERTS)).toHaveLength(1);
    expect(w.net.to(CERTS)[0].url).toBe(`https://${TEAM}/cdn-cgi/access/certs`);
    const rotated = await accessSigner("test-key-2");
    w.net.on(CERTS, () => Response.json({ keys: [...w.signer.jwks.keys, ...rotated.jwks.keys] }));
    const token = await rotated.sign(claims());
    // Within a minute of the last fetch an unknown kid is refused without asking again...
    expect((await handle(get("/review", token), w.env, w.deps)).status).toBe(403);
    expect(w.net.to(CERTS)).toHaveLength(1);
    // ...after that the keys are fetched again and the rotated key is accepted.
    const later = { ...w.deps, now: () => new Date(NOW.getTime() + 2 * 60_000) };
    expect((await handle(get("/review", token), w.env, later)).status).toBe(200);
    expect(w.net.to(CERTS)).toHaveLength(2);
  });

  it("guards the slides and the decisions too", async () => {
    const w = await world();
    for (const req of [get("/review/slides/7/slide_01.webp"),
      new Request("https://pontonomada.pt/review/decision", { method: "POST", body: "{}" })]) {
      expect((await handle(req, w.env, w.deps)).status).toBe(403);
    }
  });
});

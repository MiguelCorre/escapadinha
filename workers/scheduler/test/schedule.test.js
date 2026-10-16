// The scheduler (D41): the dispatch request, the skip rules, failures, and the token kept out of
// every log line and error. GitHub is a fake fetch; nothing here touches the network.
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import worker from "../src/index.js";
import { main, WORKER_MISSED } from "../src/fallback.js";
import { API, INPUTS, ScheduleError, recentRun, redact, settings, tick, USER_AGENT } from "../src/schedule.js";

const TOKEN = "github_pat_11FAKE0TEST0ONLY_abcdefghijklmnopqrstuvwxyz0123456789";
const NOW = new Date("2026-10-16T10:17:00Z");
const ENV = Object.freeze({
  GITHUB_ACTIONS_TOKEN: TOKEN,
  GITHUB_REPOSITORY: "MiguelCorre/escapadinha",
  WORKFLOW: "pipeline.yml",
  REF: "master",
  SKIP_IF_RUN_WITHIN_MINUTES: "45",
});
const WORKFLOW_URL = `${API}/repos/MiguelCorre/escapadinha/actions/workflows/pipeline.yml`;

const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const minutesAgo = (minutes) => new Date(NOW.getTime() - minutes * 60_000).toISOString();
const run = (minutes, extra = {}) => ({
  id: 1000 + minutes, run_number: 60 + minutes, event: "workflow_dispatch", status: "completed",
  conclusion: "success", created_at: minutesAgo(minutes), ...extra,
});

/** A fake GitHub: answers the workflow, its runs and the dispatch; records every request. */
function github({ workflow = () => json({ id: 1, state: "active" }), runs = () => json({ workflow_runs: [] }),
  dispatch = () => new Response(null, { status: 204 }) } = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET", headers: { ...init.headers },
      body: init.body });
    const path = new URL(String(url)).pathname;
    if (init.method === "POST") return dispatch();
    return path.endsWith("/runs") ? runs() : workflow();
  };
  return { fetch, calls };
}

function recorder() {
  const lines = [];
  const at = (level) => (...args) => lines.push({ level, text: args.join(" ") });
  return { lines, log: { log: at("log"), warn: at("warn"), error: at("error") } };
}

/** Every line logged and every error message, to check none holds the token. */
function everything(lines, error) {
  return [...lines.map((l) => l.text), ...(error ? [error.message, String(error.stack)] : [])].join("\n");
}

describe("the dispatch", () => {
  test("POSTs a routine run of pipeline.yml on master with the token as a Bearer header", async () => {
    const gh = github();
    const { log, lines } = recorder();
    const outcome = await tick({ env: ENV, fetch: gh.fetch, now: NOW, log });

    assert.equal(outcome.action, "dispatched");
    const posts = gh.calls.filter((c) => c.method === "POST");
    assert.equal(posts.length, 1);
    const [post] = posts;
    assert.equal(post.url, `${WORKFLOW_URL}/dispatches`);
    assert.deepEqual(JSON.parse(post.body), { ref: "master", inputs: { full: "false" } });
    assert.deepEqual(post.headers, {
      Authorization: `Bearer ${TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": USER_AGENT,
      "Content-Type": "application/json",
    });
    assert.deepEqual(lines, [{ level: "log",
      text: "Dispatched pipeline.yml on master: no run in the last 45 min." }]);
  });

  test("reads the workflow and its newest runs first, with the same headers and no body", async () => {
    const gh = github();
    await tick({ env: ENV, fetch: gh.fetch, now: NOW, log: recorder().log });
    const [workflow, runs, post] = gh.calls;
    assert.equal(workflow.url, WORKFLOW_URL);
    assert.equal(runs.url, `${WORKFLOW_URL}/runs?per_page=20&exclude_pull_requests=true`);
    for (const read of [workflow, runs]) {
      assert.equal(read.method, "GET");
      assert.equal(read.body, undefined);
      assert.equal(read.headers.Authorization, `Bearer ${TOKEN}`);
      assert.equal(read.headers["User-Agent"], USER_AGENT);
      assert.equal(read.headers.Accept, "application/vnd.github+json");
    }
    assert.equal(post.method, "POST");
    assert.equal(gh.calls.length, 3);
  });

  test("the inputs are only the ones pipeline.yml declares, as strings", () => {
    assert.deepEqual(Object.keys(INPUTS), ["full"]);
    assert.ok(Object.values(INPUTS).every((v) => typeof v === "string"));
  });
});

describe("skip logic", () => {
  test("a run created within the window serves the tick, whatever its event or outcome", async () => {
    for (const recent of [
      run(10),                                                    // the last tick's own, done
      run(44, { event: "repository_dispatch" }),                  // a review decision
      run(5, { status: "in_progress", conclusion: null }),        // still running
      run(1, { status: "queued", conclusion: null }),
      run(30, { conclusion: "failure" }),
    ]) {
      const gh = github({ runs: () => json({ workflow_runs: [run(200), recent] }) });
      const { log, lines } = recorder();
      const outcome = await tick({ env: ENV, fetch: gh.fetch, now: NOW, log });
      assert.equal(outcome.action, "skipped", JSON.stringify(recent));
      assert.ok(!gh.calls.some((c) => c.method === "POST"));
      assert.match(lines[0].text, new RegExp(`run ${recent.run_number} \\(${recent.event}`));
      assert.match(lines[0].text, /within 45 min: nothing dispatched\.$/);
    }
  });

  test("runs older than the window don't count, so the next tick dispatches", async () => {
    const gh = github({ runs: () => json({ workflow_runs: [run(46), run(120), run(500)] }) });
    const outcome = await tick({ env: ENV, fetch: gh.fetch, now: NOW, log: recorder().log });
    assert.equal(outcome.action, "dispatched");
  });

  test("the fallback's window is its own setting", async () => {
    const env = { ...ENV, SKIP_IF_RUN_WITHIN_MINUTES: "180" };
    const busy = github({ runs: () => json({ workflow_runs: [run(170)] }) });
    assert.equal((await tick({ env, fetch: busy.fetch, now: NOW, log: recorder().log })).action, "skipped");
    const quiet = github({ runs: () => json({ workflow_runs: [run(181)] }) });
    assert.equal((await tick({ env, fetch: quiet.fetch, now: NOW, log: recorder().log })).action, "dispatched");
  });

  test("recentRun picks the newest run inside the window and ignores runs without a time", () => {
    const runs = [run(50), run(20), run(30), { id: 7 }, { id: 8, created_at: "not a date" }];
    assert.equal(recentRun(runs, NOW, 45).run_number, run(20).run_number);
    assert.equal(recentRun(runs, NOW, 15), null);
    assert.equal(recentRun([], NOW, 45), null);
    assert.equal(recentRun([run(45)], NOW, 45), null);           // exactly the window: not within
  });

  test("a disabled workflow (gh workflow disable, during a restore) is left alone", async () => {
    const gh = github({ workflow: () => json({ id: 1, state: "disabled_manually" }) });
    const { log, lines } = recorder();
    const outcome = await tick({ env: ENV, fetch: gh.fetch, now: NOW, log });
    assert.equal(outcome.action, "skipped");
    assert.equal(gh.calls.length, 1);
    assert.equal(lines[0].text, "pipeline.yml is disabled manually: nothing dispatched.");
  });

  test("when GitHub can't answer the reads, the tick dispatches anyway and says so", async () => {
    const down = () => json({ message: "Server Error" }, 502);
    for (const gh of [
      github({ workflow: down, runs: down }),
      github({ workflow: () => { throw new TypeError("fetch failed"); },
        runs: () => new Response("<html>gateway</html>", { status: 504 }) }),
      github({ runs: () => json({ unexpected: true }) }),
    ]) {
      const { log, lines } = recorder();
      const outcome = await tick({ env: ENV, fetch: gh.fetch, now: NOW, log });
      assert.equal(outcome.action, "dispatched");
      for (const warning of lines.filter((l) => l.level === "warn")) {
        assert.match(warning.text, /^Could not read .*: dispatching anyway\.$/);
      }
    }
    const { log, lines } = recorder();
    await tick({ env: ENV, fetch: github({ workflow: down, runs: down }).fetch, now: NOW, log });
    assert.deepEqual(lines.filter((l) => l.level === "warn").map((l) => l.text), [
      "Could not read the workflow pipeline.yml (HTTP 502: Server Error): dispatching anyway.",
      "Could not read the runs of pipeline.yml (HTTP 502: Server Error): dispatching anyway.",
    ]);
  });
});

describe("failures", () => {
  test("a refused dispatch is logged with GitHub's status and message, and throws", async () => {
    const gh = github({ dispatch: () => json({ message: "Bad credentials" }, 401) });
    const { log, lines } = recorder();
    await assert.rejects(tick({ env: ENV, fetch: gh.fetch, now: NOW, log }), (err) => {
      assert.ok(err instanceof ScheduleError);
      assert.equal(err.message, "Dispatch of pipeline.yml refused: HTTP 401: Bad credentials.");
      return true;
    });
    assert.deepEqual(lines.filter((l) => l.level === "error").map((l) => l.text),
      ["Dispatch of pipeline.yml refused: HTTP 401: Bad credentials."]);
  });

  test("a dispatch GitHub never answered is a failure too", async () => {
    const gh = github({ dispatch: () => { throw new TypeError("fetch failed"); } });
    const { log, lines } = recorder();
    await assert.rejects(tick({ env: ENV, fetch: gh.fetch, now: NOW, log }),
      /Dispatch of pipeline\.yml failed: GitHub did not answer \(TypeError: fetch failed\)\./);
    assert.equal(lines.at(-1).level, "error");
  });

  test("a missing token stops before any request", async () => {
    const gh = github();
    const { log, lines } = recorder();
    for (const token of [undefined, "", "   "]) {
      await assert.rejects(tick({ env: { ...ENV, GITHUB_ACTIONS_TOKEN: token }, fetch: gh.fetch, now: NOW, log }),
        /GITHUB_ACTIONS_TOKEN is not set/);
    }
    assert.equal(gh.calls.length, 0);
    assert.ok(lines.every((l) => l.level === "error"));
  });

  test("settings refuse a malformed repository, workflow, branch or window", () => {
    assert.deepEqual(settings(ENV), { token: TOKEN, repository: "MiguelCorre/escapadinha",
      workflow: "pipeline.yml", ref: "master", windowMinutes: 45 });
    for (const [name, value] of [
      ["GITHUB_REPOSITORY", "escapadinha"], ["GITHUB_REPOSITORY", "a/b/c"],
      ["GITHUB_REPOSITORY", "evil.com/x?y"], ["WORKFLOW", "pipeline"], ["WORKFLOW", "../x.yml"],
      ["REF", ""], ["REF", "master branch"], ["SKIP_IF_RUN_WITHIN_MINUTES", ""],
      ["SKIP_IF_RUN_WITHIN_MINUTES", "0"], ["SKIP_IF_RUN_WITHIN_MINUTES", "4.5"],
      ["SKIP_IF_RUN_WITHIN_MINUTES", "2000"], ["SKIP_IF_RUN_WITHIN_MINUTES", "-5"],
    ]) {
      assert.throws(() => settings({ ...ENV, [name]: value }), ScheduleError, `${name}=${value}`);
    }
  });
});

describe("the token never reaches a log line or an error", () => {
  // GitHub (or something in between) echoing the token back, in every place a text comes from
  const echoes = {
    "a refusal's message": github({ dispatch: () => json({ message: `Bad credentials for ${TOKEN}` }, 401) }),
    "a network error's text": github({
      dispatch: () => { throw new Error(`connect failed, Authorization: Bearer ${TOKEN}`); } }),
    "the reads' warnings": github({ workflow: () => json({ message: `no access with ${TOKEN}` }, 403),
      runs: () => { throw new Error(`socket closed ${TOKEN}`); } }),
    "a skipped run's fields": github({ runs: () => json({ workflow_runs: [run(3, { event: `x${TOKEN}` })] }) }),
    "a plain dispatch": github(),
  };
  for (const [name, gh] of Object.entries(echoes)) {
    test(name, async () => {
      const { log, lines } = recorder();
      let error;
      try {
        await tick({ env: ENV, fetch: gh.fetch, now: NOW, log });
      } catch (err) {
        error = err;
      }
      assert.ok(lines.length > 0);
      const text = everything(lines, error);
      assert.ok(!text.includes(TOKEN), text);
      assert.ok(!text.includes(TOKEN.slice(0, 20)), text);
    });
  }

  test("a token put by mistake in another setting is redacted from the refusal", async () => {
    const env = { ...ENV, GITHUB_REPOSITORY: TOKEN };
    const { log, lines } = recorder();
    const error = await tick({ env, fetch: github().fetch, now: NOW, log }).catch((err) => err);
    assert.ok(error instanceof ScheduleError);
    assert.ok(!everything(lines, error).includes(TOKEN));
    assert.match(error.message, /GITHUB_REPOSITORY must be owner\/name, not "\*\*\*"/);
  });

  test("redact replaces every occurrence and leaves text alone without a token", () => {
    assert.equal(redact(`a ${TOKEN} b ${TOKEN}`, TOKEN), "a *** b ***");
    assert.equal(redact("nothing to hide", ""), "nothing to hide");
  });
});

describe("the Worker", () => {
  test("its cron dispatches with the scheduled time as now, through the global fetch", async () => {
    const gh = github({ runs: () => json({ workflow_runs: [run(50)] }) });   // 50 min before NOW
    const original = globalThis.fetch;
    const originalLog = console.log;
    const logged = [];
    globalThis.fetch = gh.fetch;
    console.log = (...args) => logged.push(args.join(" "));
    try {
      await worker.scheduled({ scheduledTime: NOW.getTime(), cron: "17 */2 * * *" }, { ...ENV });
    } finally {
      globalThis.fetch = original;
      console.log = originalLog;
    }
    assert.equal(gh.calls.filter((c) => c.method === "POST").length, 1);
    assert.deepEqual(logged, ["Dispatched pipeline.yml on master: no run in the last 45 min."]);

    // The window is measured from the trigger's scheduled time, not the clock at hand: a run
    // 10 minutes before a scheduled time years ago still serves that tick.
    const past = new Date("2020-01-01T00:17:00Z");
    const busy = github({ runs: () => json({ workflow_runs: [
      { ...run(0), created_at: new Date(past.getTime() - 10 * 60_000).toISOString() }] }) });
    globalThis.fetch = busy.fetch;
    console.log = () => {};
    try {
      await worker.scheduled({ scheduledTime: past.getTime(), cron: "17 */2 * * *" }, { ...ENV });
    } finally {
      globalThis.fetch = original;
      console.log = originalLog;
    }
    assert.ok(!busy.calls.some((c) => c.method === "POST"));
  });

  test("a failed dispatch rejects, so Cloudflare records the invocation as failed", async () => {
    const gh = github({ dispatch: () => json({ message: "Not Found" }, 404) });
    const original = globalThis.fetch;
    const originalError = console.error;
    const logged = [];
    globalThis.fetch = gh.fetch;
    console.error = (...args) => logged.push(args.join(" "));
    try {
      await assert.rejects(worker.scheduled({ scheduledTime: NOW.getTime(), cron: "17 */2 * * *" }, { ...ENV }),
        ScheduleError);
    } finally {
      globalThis.fetch = original;
      console.error = originalError;
    }
    assert.deepEqual(logged, ["Dispatch of pipeline.yml refused: HTTP 404: Not Found."]);
  });
});

describe("the Actions fallback", () => {
  const env = { ...ENV, SKIP_IF_RUN_WITHIN_MINUTES: "180" };

  test("exits 0 when a run started within its window: the Worker is doing its job", async () => {
    const gh = github({ runs: () => json({ workflow_runs: [run(100)] }) });
    assert.equal(await main({ env, fetch: gh.fetch, now: NOW, log: recorder().log }), 0);
    assert.ok(!gh.calls.some((c) => c.method === "POST"));
  });

  test("dispatches and exits 1 when nothing ran for 3 h, so GitHub e-mails Miguel", async () => {
    const gh = github({ runs: () => json({ workflow_runs: [run(200)] }) });
    const { log, lines } = recorder();
    assert.equal(await main({ env, fetch: gh.fetch, now: NOW, log }), 1);
    assert.equal(gh.calls.filter((c) => c.method === "POST").length, 1);
    assert.deepEqual(lines.map((l) => l.text), [
      "Dispatched pipeline.yml on master: no run in the last 180 min.", WORKER_MISSED]);
  });

  test("exits 1 when the dispatch fails, the reason already logged without the token", async () => {
    const gh = github({ dispatch: () => json({ message: `Resource not accessible ${TOKEN}` }, 403) });
    const { log, lines } = recorder();
    assert.equal(await main({ env, fetch: gh.fetch, now: NOW, log }), 1);
    assert.equal(lines.at(-1).text, "Dispatch of pipeline.yml refused: HTTP 403: Resource not accessible ***.");
  });

  test("exits 0 while the pipeline workflow is disabled", async () => {
    const gh = github({ workflow: () => json({ state: "disabled_manually" }) });
    assert.equal(await main({ env, fetch: gh.fetch, now: NOW, log: recorder().log }), 0);
  });
});

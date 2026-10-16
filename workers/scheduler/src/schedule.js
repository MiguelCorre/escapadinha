// @ts-check
/**
 * The 2-hourly schedule (DECISIONS D41): dispatch the pipeline workflow on GitHub unless a run of
 * it started a short while ago. One tick, shared by the Cloudflare Worker (`index.js`, a Cron
 * Trigger every 2 h, window 45 min) and the Actions fallback (`fallback.js`, every 6 h, window
 * 180 min).
 *
 * Pure apart from what is passed in (fetch, the clock, the log), so the tests run it without a
 * network. The token only ever goes into the Authorization header: every line logged and every
 * error message goes through `redact` first.
 */

export const API = "https://api.github.com";
export const USER_AGENT = "pontonomada-scheduler";
const API_VERSION = "2022-11-28";
/** A routine run: `run_path` decides fast or full (D25). The workflow declares `full`. */
export const INPUTS = Object.freeze({ full: "false" });
const RUNS_PER_PAGE = 20;      // newest first: far more than ever start within 3 h

export class ScheduleError extends Error {
  /** @param {string} message */
  constructor(message) {
    super(message);
    this.name = "ScheduleError";
  }
}

/**
 * @typedef {{ token: string, repository: string, workflow: string, ref: string,
 *             windowMinutes: number }} Settings
 * @typedef {{ log: (line: string) => void, warn: (line: string) => void,
 *             error: (line: string) => void }} Log
 * @typedef {{ id?: number, run_number?: number, event?: string, status?: string,
 *             conclusion?: string | null, created_at?: string }} WorkflowRun
 * @typedef {{ action: "dispatched" | "skipped", reason: string }} Outcome
 */

/** `text` with every occurrence of the token replaced. */
export function redact(text, token) {
  const value = String(text);
  return token ? value.split(token).join("***") : value;
}

/**
 * The tick's settings from the Worker's vars and secret (or the fallback job's environment).
 * @param {Record<string, unknown>} env
 * @returns {Settings}
 */
export function settings(env) {
  const token = String(env.GITHUB_ACTIONS_TOKEN ?? "").trim();
  if (!token) {
    throw new ScheduleError("GITHUB_ACTIONS_TOKEN is not set: add it as the Worker's secret "
      + "(docs/runbooks/agendamento.md)");
  }
  const repository = String(env.GITHUB_REPOSITORY ?? "");
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository)) {
    throw new ScheduleError(`GITHUB_REPOSITORY must be owner/name, not "${repository}"`);
  }
  const workflow = String(env.WORKFLOW ?? "");
  if (!/^[\w.-]+\.ya?ml$/.test(workflow)) {
    throw new ScheduleError(`WORKFLOW must be a workflow file name such as pipeline.yml, not "${workflow}"`);
  }
  const ref = String(env.REF ?? "");
  if (!/^[\w./-]+$/.test(ref)) throw new ScheduleError(`REF must be a branch name, not "${ref}"`);
  const raw = String(env.SKIP_IF_RUN_WITHIN_MINUTES ?? "");
  const windowMinutes = Number(raw);
  if (!/^\d+$/.test(raw) || windowMinutes < 1 || windowMinutes > 24 * 60) {
    throw new ScheduleError(`SKIP_IF_RUN_WITHIN_MINUTES must be whole minutes (1 to 1440), not "${raw}"`);
  }
  return { token, repository, workflow, ref, windowMinutes };
}

/**
 * The newest run created less than `windowMinutes` before `now`, whatever its event or outcome
 * (a run still queued or in progress counts too), else null.
 * @param {WorkflowRun[]} runs
 * @param {Date} now
 * @param {number} windowMinutes
 * @returns {WorkflowRun | null}
 */
export function recentRun(runs, now, windowMinutes) {
  const since = now.getTime() - windowMinutes * 60_000;
  const created = (/** @type {WorkflowRun} */ run) => Date.parse(run.created_at ?? "");
  return runs.filter((run) => created(run) > since)
    .sort((a, b) => created(b) - created(a))[0] ?? null;
}

/**
 * One tick: (1) a workflow that isn't active (`gh workflow disable`, e.g. while a backup is
 * restored) is left alone; (2) a run created within the window means the schedule is already
 * served; (3) otherwise dispatch a routine run. The two reads are advice: when GitHub can't
 * answer them the tick dispatches anyway (a double run is cheaper than a missed one, and the R2
 * lock serialises runs, D21). A refused or unanswered dispatch throws a `ScheduleError`, after
 * logging it.
 *
 * @param {{ env: Record<string, unknown>, fetch: typeof fetch, now: Date, log: Log }} deps
 * @returns {Promise<Outcome>}
 */
export async function tick({ env, fetch: fetchFn, now, log }) {
  const secret = String(env.GITHUB_ACTIONS_TOKEN ?? "").trim();
  const clean = (/** @type {unknown} */ text) => redact(String(text), secret);
  try {
    const s = settings(env);
    const workflowUrl = `${API}/repos/${s.repository}/actions/workflows/${s.workflow}`;
    /** @param {string} method @param {string} url @param {unknown} [body] */
    const call = (method, url, body) => fetchFn(url, {
      method,
      headers: {
        Authorization: `Bearer ${s.token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    /** @param {string} what @param {string} url @returns {Promise<any>} */
    const read = async (what, url) => {
      try {
        const res = await call("GET", url);
        if (res.ok) return await res.json();
        log.warn(clean(`Could not read ${what} (${await refusal(res)}): dispatching anyway.`));
      } catch (err) {               // no answer, or not JSON
        log.warn(clean(`Could not read ${what} (${errorText(err)}): dispatching anyway.`));
      }
      return null;
    };

    const workflow = await read(`the workflow ${s.workflow}`, workflowUrl);
    if (typeof workflow?.state === "string" && workflow.state !== "active") {
      return skipped(log, clean(`${s.workflow} is ${workflow.state.replaceAll("_", " ")}: `
        + "nothing dispatched."));
    }
    const page = await read(`the runs of ${s.workflow}`,
      `${workflowUrl}/runs?per_page=${RUNS_PER_PAGE}&exclude_pull_requests=true`);
    const recent = recentRun(Array.isArray(page?.workflow_runs) ? page.workflow_runs : [], now,
      s.windowMinutes);
    if (recent) {
      const minutes = Math.max(0, Math.round((now.getTime() - Date.parse(recent.created_at ?? "")) / 60_000));
      const state = [recent.status, recent.conclusion].filter(Boolean).join(", ");
      return skipped(log, clean(`${s.workflow} run ${recent.run_number ?? recent.id} (${recent.event}`
        + `${state ? `, ${state}` : ""}) started ${minutes} min ago, within ${s.windowMinutes} min: `
        + "nothing dispatched."));
    }

    let res;
    try {
      res = await call("POST", `${workflowUrl}/dispatches`, { ref: s.ref, inputs: { ...INPUTS } });
    } catch (err) {
      throw new ScheduleError(`Dispatch of ${s.workflow} failed: GitHub did not answer (${errorText(err)}).`);
    }
    if (!res.ok) throw new ScheduleError(`Dispatch of ${s.workflow} refused: ${await refusal(res)}.`);
    const reason = `Dispatched ${s.workflow} on ${s.ref}: no run in the last ${s.windowMinutes} min.`;
    log.log(reason);
    return { action: "dispatched", reason };
  } catch (err) {               // the one place a failure is logged, redacted
    const message = clean(err instanceof ScheduleError ? err.message : errorText(err));
    log.error(message);
    throw new ScheduleError(message);
  }
}

/** @param {Log} log @param {string} reason @returns {Outcome} */
function skipped(log, reason) {
  log.log(reason);
  return { action: "skipped", reason };
}

/** "HTTP 401: Bad credentials": the status and GitHub's own message, never the body as a whole. */
async function refusal(/** @type {Response} */ res) {
  let message = "";
  try {
    const body = await res.json();
    if (typeof body?.message === "string") message = body.message.slice(0, 300);
  } catch {
    // not GitHub's JSON (a proxy's page): the status says enough
  }
  return `HTTP ${res.status}${message ? `: ${message}` : ""}`;
}

function errorText(/** @type {unknown} */ err) {
  return err instanceof Error ? `${err.name}: ${err.message}` : String(err);
}

// @ts-check
/**
 * The Actions fallback of the schedule (.github/workflows/pipeline-fallback.yml, DECISIONS D41):
 * the Worker's tick, run with Node on GitHub's own best-effort cron, with a 3 h window. It only
 * dispatches when no pipeline run started in the last 3 h, i.e. when the Worker missed its runs.
 *
 * Exit 0 when it skipped. Exit 1 when it had to dispatch (the job fails on purpose: GitHub e-mails
 * a failed scheduled run, and that is how Miguel learns the Worker stopped) or when the dispatch
 * itself failed.
 */
import { pathToFileURL } from "node:url";
import { ScheduleError, tick } from "./schedule.js";

export const WORKER_MISSED = "The fallback had to dispatch the pipeline, so the Cloudflare Worker "
  + "missed its runs (token expired or revoked, Worker deleted or failing): see "
  + "docs/runbooks/agendamento.md, \"Se alguma coisa falhar\". This job fails on purpose so that "
  + "GitHub e-mails you.";

/**
 * @param {Parameters<typeof tick>[0]} deps
 * @returns {Promise<number>} the exit code
 */
export async function main(deps) {
  try {
    const outcome = await tick(deps);
    if (outcome.action === "skipped") return 0;
    deps.log.error(WORKER_MISSED);
    return 1;
  } catch (err) {
    if (!(err instanceof ScheduleError)) throw err;   // tick turns every failure into one
    return 1;                                          // already logged, redacted
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main({
    env: process.env,
    fetch: (input, init) => fetch(input, init),
    now: new Date(),
    log: console,
  });
}

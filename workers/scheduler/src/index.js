// @ts-check
/**
 * The scheduler Worker (DECISIONS D41): its Cron Trigger (wrangler.toml, every 2 h) dispatches
 * the pipeline workflow unless a run started in the last SKIP_IF_RUN_WITHIN_MINUTES. No fetch
 * handler and no workers.dev route: nothing can call it over HTTP. A failed dispatch is logged
 * (Workers Logs) and rejects, so Cloudflare records the invocation as failed.
 */
import { tick } from "./schedule.js";

export default {
  /**
   * @param {{ scheduledTime: number, cron: string }} controller
   * @param {Record<string, unknown>} env  vars from wrangler.toml + the GITHUB_ACTIONS_TOKEN secret
   */
  async scheduled(controller, env) {
    await tick({
      env,
      fetch: (input, init) => fetch(input, init),   // never detached from the global (Workers)
      now: new Date(controller.scheduledTime),
      log: console,
    });
  },
};

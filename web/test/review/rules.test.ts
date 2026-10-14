// The Function's review rules are a port of src/escapadinha/review.py: both sides are checked
// against contract/review/v1/fixtures/review-rules.json (tests/test_review_rules_cases.py runs
// the pipeline's), so the tables can't drift apart (D29).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  checkDecision, DECISION_PT, DECISIONS, OPEN_STATUSES, ReviewError, STATUS_PT, TRANSITIONS,
} from "../../functions/_lib/review/rules";
import { CONTRACT } from "./helpers";

const RULES = JSON.parse(readFileSync(resolve(CONTRACT, "fixtures/review-rules.json"), "utf8"));

describe("review rules: shared with the pipeline", () => {
  it("has the same tables", () => {
    expect(Object.fromEntries(Object.entries(TRANSITIONS).map(([k, v]) => [k, [...v].sort()])))
      .toEqual(RULES.transitions);
    expect(STATUS_PT).toEqual(RULES.status_pt);
    expect(DECISIONS).toEqual(RULES.decisions);
    expect(DECISION_PT).toEqual(RULES.decision_pt);
    expect(OPEN_STATUSES).toEqual(RULES.open_statuses);
  });

  it.each(RULES.check_decision.map((c: any, i: number) => [`${c.kind}-${c.status}-${i}`, c]))(
    "check_decision %s", (_, c: any) => {
      const run = () => checkDecision(c.kind, c.status, { affiliateUrl: c.affiliate_url, postUrl: c.post_url ?? null });
      if (c.expected.error) {
        let error: unknown;
        try { run(); } catch (exc) { error = exc; }
        expect(error).toBeInstanceOf(ReviewError);
        expect((error as ReviewError).message).toBe(c.expected.error);
      } else {
        expect(run()).toBe(c.expected.status);
      }
    });
});

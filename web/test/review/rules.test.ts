// The Function's review rules are a port of src/escapadinha/review.py: both sides are checked
// against contract/review/v1/fixtures/review-rules.json (tests/test_review_rules_cases.py runs
// the pipeline's), so the tables can't drift apart (D29).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  checkDecision, CONFIDENCE_PT, DECISION_PT, DECISIONS, OPEN_STATUSES, ReviewError, STATUS_PT, TRANSITIONS,
} from "../../functions/_lib/review/rules";
import { newEvent } from "../../functions/_lib/review/events";
import { CONTRACT } from "./helpers";

const RULES = JSON.parse(readFileSync(resolve(CONTRACT, "fixtures/review-rules.json"), "utf8"));

/** it.each rows: [name, case]. */
const rows = (cases: any[], name: (c: any, i: number) => string): [string, any][] =>
  cases.map((c, i) => [name(c, i), c]);

describe("review rules: shared with the pipeline", () => {
  it("has the same tables", () => {
    expect(Object.fromEntries(Object.entries(TRANSITIONS).map(([k, v]) => [k, [...v].sort()])))
      .toEqual(RULES.transitions);
    expect(STATUS_PT).toEqual(RULES.status_pt);
    expect(DECISIONS).toEqual(RULES.decisions);
    expect(DECISION_PT).toEqual(RULES.decision_pt);
    expect(CONFIDENCE_PT).toEqual(RULES.confidence_pt);
    expect(OPEN_STATUSES).toEqual(RULES.open_statuses);
  });

  it.each(rows(RULES.check_decision, (c, i) => `${c.kind}-${c.status}-${i}`))(
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

  it.each(rows(RULES.new_event_text.cases, (c) => JSON.stringify(c.given)))(
    "event text %s like Event.new", (_, c: any) => {
      const event = newEvent("published", 1, { id: "x", actor: "test", now: new Date("2026-10-14T00:00:00Z"),
        note: c.given, postUrl: c.given });
      expect([event.note, event.post_url]).toEqual([c.expected, c.expected]);
    });
});

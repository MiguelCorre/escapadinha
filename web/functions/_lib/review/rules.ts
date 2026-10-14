// Which decisions a reviewer may make, ported from src/escapadinha/review.py (TRANSITIONS,
// STATUS_PT, DECISIONS, DECISION_PT, check_decision) and db.OPEN_STATUSES. Both sides are checked
// against contract/review/v1/fixtures/review-rules.json (web/test/review/rules.test.ts,
// tests/test_review_rules_cases.py): change the three together. The Function pre-checks against the
// snapshot's statuses so Miguel hears a refusal at once; the pipeline's applier
// (review_events.apply_pending) checks again against the status the deal has when it applies the
// event, so a stale snapshot can never move a deal the wrong way (D26).
import type { DecisionType, SnapshotDeal } from "./types";

type Status = SnapshotDeal["status"];

export class ReviewError extends Error {
  constructor(message: string, readonly status = 409) {
    super(message);
  }
}

export const TRANSITIONS: Record<Status, Status[]> = {
  new: ["rendered", "rejected", "expired"],
  rendered: ["approved", "rejected", "expired"],
  approved: ["published", "rejected", "expired"],
  rejected: [],
  expired: [],
  published: [],
};

export const STATUS_PT: Record<Status, string> = {
  new: "novo", rendered: "por rever", approved: "aprovado",
  published: "publicado", rejected: "rejeitado", expired: "expirado",
};

export const DECISIONS: Record<DecisionType, Status> = { approve: "approved", reject: "rejected", published: "published" };
export const DECISION_PT: Record<DecisionType, string> = { approve: "aprovar", reject: "rejeitar", published: "marcar como publicado" };

/** db.OPEN_STATUSES: deals the live check still prices. */
export const OPEN_STATUSES: Status[] = ["new", "rendered", "approved"];

export function isDecision(kind: unknown): kind is DecisionType {
  return typeof kind === "string" && Object.hasOwn(DECISIONS, kind);
}

/** review.check_decision: the status a decision moves a deal to, or ReviewError (pt-PT). */
export function checkDecision(kind: string, status: Status,
  { affiliateUrl, postUrl }: { affiliateUrl: string | null; postUrl?: string | null }): Status {
  if (!isDecision(kind)) throw new ReviewError(`Decisão desconhecida: '${kind}'.`, 400);
  const target = DECISIONS[kind];
  if (!(TRANSITIONS[status] ?? []).includes(target)) {
    throw new ReviewError(`Não é possível passar de '${STATUS_PT[status] ?? status}' para '${STATUS_PT[target]}'.`);
  }
  if (kind === "approve" && !affiliateUrl) {
    throw new ReviewError("Este deal ainda não tem link de afiliado. Volta a renderizar.");
  }
  if (kind === "published" && postUrl && !/^https?:\/\//.test(postUrl)) {
    throw new ReviewError("O link do post tem de começar por https://");
  }
  return target;
}

// Review events written by the Function (D26, D29), in the shape and at the keys the pipeline's
// writer uses (src/escapadinha/review_events.py: Event.new, Event.key, Event.to_json, write).
// The Function only ever adds objects under review/events/pending/; the pipeline applies them.
import { utcIso } from "./live-check";
import type { Bucket, DecisionType, LiveCheck, ReviewEvent, Snapshot } from "./types";

export const PENDING = "review/events/pending/";
export const SNAPSHOT = "review/snapshot.json";

/** "2026-10-14T09:30:00Z" -> "20261014T093000Z" (Event.key's `%Y%m%dT%H%M%SZ`). */
export function stamp(utc: string): string {
  return utc.replace(/[-:]/g, "").replace(/\.\d+/, "");
}

/** Event.new: created_at to the second; note and post_url kept as given, only an empty or missing
 * one becomes null (Python's `note or None`; shared cases in review-rules.json). */
export function newEvent(type: DecisionType, dealId: number, { id, actor, now, note, postUrl, liveCheck }: {
  id: string; actor: string; now: Date; note?: string | null; postUrl?: string | null; liveCheck?: LiveCheck | null;
}): ReviewEvent {
  return {
    version: 1, id, type, deal_id: dealId, created_at: utcIso(now), actor,
    note: note || null, post_url: postUrl || null, live_check: liveCheck ?? null,
  };
}

export function eventKey(event: ReviewEvent): string {
  return `${PENDING}${stamp(event.created_at)}-${event.id}.json`;
}

export async function writeEvent(store: Bucket, event: ReviewEvent): Promise<string> {
  const key = eventKey(event);
  await store.put(key, JSON.stringify(event, null, 2), { httpMetadata: { contentType: "application/json" } });
  return key;
}

export async function listKeys(store: Bucket, prefix: string): Promise<string[]> {
  const keys: string[] = [];
  let cursor: string | undefined;
  do {
    const page = await store.list({ prefix, cursor });
    keys.push(...page.objects.map((o) => o.key));
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return keys;
}

export async function readSnapshot(store: Bucket): Promise<Snapshot | null> {
  const obj = await store.get(SNAPSHOT);
  return obj ? (JSON.parse(await obj.text()) as Snapshot) : null;
}

/** Decisions not applied yet: the snapshot's `pending_events`, plus events written since it was
 * made. An older event still under pending/ but not in the snapshot was already applied by the
 * run that made it (it is archived by the next run, D26), so it doesn't count. */
export async function pendingEvents(store: Bucket, snapshot: Snapshot): Promise<ReviewEvent[]> {
  const events = [...snapshot.pending_events];
  const known = new Set(events.map((e) => e.id));
  const since = stamp(snapshot.generated_at);
  for (const key of await listKeys(store, PENDING)) {
    const name = key.slice(PENDING.length);
    if (name.slice(0, 16) < since) continue;
    const obj = await store.get(key);
    if (!obj) continue;                                   // settled meanwhile
    try {
      const event = JSON.parse(await obj.text()) as ReviewEvent;
      if (event && typeof event.deal_id === "number" && !known.has(event.id)) {
        events.push(event);
        known.add(event.id);
      }
    } catch {
      // malformed: the applier archives it as such
    }
  }
  return events.sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/** One repository_dispatch (`review-decision`) so the pipeline applies the event within minutes
 * (D25). Returns null when GitHub accepted it, else the reason (the event stays pending). */
export async function dispatch(event: ReviewEvent, { token, repository, fetch: fetchFn }: {
  token: string; repository: string; fetch: typeof fetch;
}): Promise<string | null> {
  if (!token) return "GITHUB_DISPATCH_TOKEN em falta";
  try {
    const res = await fetchFn(`https://api.github.com/repos/${repository}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pontonomada-review",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ event_type: "review-decision",
        client_payload: { event_id: event.id, deal_id: event.deal_id, type: event.type } }),
    });
    return res.status === 204 || res.ok ? null : `HTTP ${res.status}`;
  } catch (exc) {
    return (exc as Error).message || "sem resposta";
  }
}

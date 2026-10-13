"""Per-run raw archive: every API response of a run as one gzip JSON object.

Traceability: rendered price → promotion → observation → first run (`run_id`) →
`fetch_runs.archive_key` → this object, which holds the payload the price came from.
"""

from __future__ import annotations

import gzip
import json
import sqlite3

from escapadinha.storage import db
from escapadinha.storage.objects import ObjectStore

FORMAT = 1


def run_key(run_id: int) -> str:
    return f"archive/runs/{run_id:07d}.json.gz"


def write_run(store: ObjectStore, conn: sqlite3.Connection, run_id: int,
              responses: list[dict], *, reconstructed: bool = False) -> str:
    """Store the run's responses and record the key on the run row."""
    key = run_key(run_id)
    body = {"format": FORMAT, "run_id": run_id, "reconstructed": reconstructed,
            "responses": responses}
    store.put(key, gzip.compress(json.dumps(body, ensure_ascii=False).encode("utf-8"), mtime=0))
    db.set_run_archive(conn, run_id, key)
    return key


def read(store: ObjectStore, key: str) -> dict:
    return json.loads(gzip.decompress(store.get(key)))


def items(archive: dict) -> list[dict]:
    """Every offer item in the archive, across responses."""
    return [item for r in archive["responses"] for item in (r["payload"].get("data") or [])]


def flush_legacy(conn: sqlite3.Connection, store: ObjectStore) -> int:
    """Archive raw payloads parked by migration 7 (one object per old run), then drop them.

    Old runs kept only the items, not whole responses, so they are grouped per route and
    marked `reconstructed`. Idempotent: a crash halfway resumes with the remaining runs.
    """
    if not db.raw_pending_exists(conn):
        return 0
    runs = db.raw_pending_runs(conn)
    for run_id in runs:
        by_route: dict[tuple[str, str], list[dict]] = {}
        for row in db.raw_pending_items(conn, run_id):
            by_route.setdefault((row["origin"], row["destination"]), []).append(
                json.loads(row["raw_json"] or "{}"))
        responses = [{"origin": o, "destination": d, "month": None, "fetched_at": None,
                      "payload": {"data": data}} for (o, d), data in by_route.items()]
        write_run(store, conn, run_id, responses, reconstructed=True)
        db.drop_raw_pending(conn, run_id)
    db.finish_raw_pending(conn)
    return len(runs)

"""SQLite access: plain SQL, one function per query. No ORM."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path

from escapadinha.models import Deal, Observation, Photo, Post

SCHEMA_VERSION = 10

# Tracked links per (observation, Travelpayouts Project) for low prices on the website (D24):
# created once through the partner links API, kept in the database because it is synced to
# R2 and a CI runner keeps no local files between runs.
PARTNER_LINKS_TABLE = """CREATE TABLE IF NOT EXISTS partner_links (
    observation_id INTEGER NOT NULL REFERENCES price_observations(id),
    project_id     INTEGER NOT NULL,             -- Travelpayouts Project ("trs")
    partner_url    TEXT,                         -- NULL when the conversion failed
    error          TEXT,
    created_at     TEXT NOT NULL,                -- UTC, last attempt
    PRIMARY KEY (observation_id, project_id)
)"""

POSTING_QUEUE_TABLE = """CREATE TABLE IF NOT EXISTS posting_queue (
    id         INTEGER PRIMARY KEY,
    deal_id    INTEGER NOT NULL REFERENCES deals(id),
    channel    TEXT    NOT NULL CHECK (channel IN ('instagram', 'telegram')),
    due_at     TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'published', 'cancelled')),
    created_at TEXT    NOT NULL,
    event_id   TEXT,
    checked_at TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    publisher  TEXT,
    result_url TEXT,
    reason     TEXT,
    settled_at TEXT,
    UNIQUE (deal_id, channel)
)"""

ROUTES_TABLE = """CREATE TABLE IF NOT EXISTS routes (
    origin               TEXT NOT NULL,              -- airport IATA (LIS, OPO, ...)
    destination          TEXT NOT NULL,              -- provider city code (LON, PAR, ...)
    destination_airports TEXT,                       -- comma-separated airport codes, if known
    city_pt              TEXT NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('europe', 'long_haul', 'domestic')),
    direct_only          INTEGER,                    -- rule overrides: NULL = the kind's default
    min_nights           INTEGER,
    max_nights           INTEGER,
    max_transfers        INTEGER,
    price_cap_eur        NUMERIC,
    status               TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dormant')),
    discovered_at        TEXT NOT NULL,
    last_observed_at     TEXT,
    PRIMARY KEY (origin, destination)
)"""

# Steps that bring an existing database from version N-1 to N.
MIGRATIONS = {
    2: ["ALTER TABLE price_observations ADD COLUMN found_date TEXT"],
    3: ["ALTER TABLE deals ADD COLUMN affiliate_url TEXT",
        "ALTER TABLE deals ADD COLUMN affiliate_error TEXT"],
    # SQLite can't alter a CHECK constraint: rebuild deals with the 'expired' status.
    4: ["""CREATE TABLE deals_v4 (
            id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL UNIQUE REFERENCES price_observations(id),
            rule TEXT NOT NULL CHECK (rule IN ('median', 'price_cap')),
            baseline_median NUMERIC, sample_size INTEGER NOT NULL, discount_pct NUMERIC,
            threshold NUMERIC NOT NULL, detected_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new' CHECK (status IN
                ('new', 'rendered', 'approved', 'rejected', 'published', 'expired')),
            affiliate_url TEXT, affiliate_error TEXT,
            last_checked_at TEXT, last_seen_price NUMERIC, expired_reason TEXT)""",
        """INSERT INTO deals_v4 (id, observation_id, rule, baseline_median, sample_size,
               discount_pct, threshold, detected_at, status, affiliate_url, affiliate_error)
           SELECT id, observation_id, rule, baseline_median, sample_size, discount_pct,
               threshold, detected_at, status, affiliate_url, affiliate_error FROM deals""",
        "DROP TABLE deals",
        "ALTER TABLE deals_v4 RENAME TO deals"],
    5: ["ALTER TABLE fetch_runs ADD COLUMN scope TEXT NOT NULL DEFAULT 'full'",
        "ALTER TABLE deals ADD COLUMN output_path TEXT",
        "ALTER TABLE deals ADD COLUMN reviewed_at TEXT",
        "ALTER TABLE deals ADD COLUMN review_note TEXT",
        "ALTER TABLE deals ADD COLUMN published_at TEXT",
        "ALTER TABLE deals ADD COLUMN post_url TEXT"],
    # Routes move from config.yaml into the database (seeded by routes.sync on first use).
    6: [ROUTES_TABLE],
    # 7 (dedup + raw archive) is a Python step, defined below `_dedupe_observations`.
    # Route discovery: English city name (photo queries) and a key/value table for
    # pipeline bookkeeping such as the last discovery time.
    8: ["ALTER TABLE routes ADD COLUMN city_en TEXT",
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"],
    # Two publication tiers: cached partner links for low prices on route pages.
    9: [PARTNER_LINKS_TABLE],
    # Posting queue (D32): Instagram slots and Telegram posts queued by approvals.
    10: [POSTING_QUEUE_TABLE,
         "CREATE INDEX IF NOT EXISTS ix_posting_due ON posting_queue (status, due_at)"],
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def utc_iso(dt: datetime | None, *, minutes: bool = False) -> str | None:
    """UTC with a 'Z' suffix, to the second (or minute): what the JSON contracts carry (review
    events and snapshot, site data) and what the review Function emits too."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ" if minutes
                                                else "%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"Database schema v{current} is newer than this code (v{SCHEMA_VERSION})")
    if current == 0:
        conn.executescript(files("escapadinha.storage").joinpath("schema.sql").read_text("utf-8"))
    else:
        for version in range(current + 1, SCHEMA_VERSION + 1):
            for step in MIGRATIONS[version]:
                step(conn) if callable(step) else conn.execute(step)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


# --- fetch runs -------------------------------------------------------------

def start_run(conn: sqlite3.Connection, source: str, scope: str = "full") -> int:
    cur = conn.execute(
        "INSERT INTO fetch_runs (source, started_at, scope) VALUES (?, ?, ?)",
        (source, _ts(utcnow()), scope),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, *, status: str, n_requests: int,
               n_observations: int, error: str | None, n_new: int | None = None) -> None:
    """`n_observations`: offers the source returned; `n_new`: of those, not stored before."""
    conn.execute(
        """UPDATE fetch_runs SET finished_at = ?, status = ?, n_requests = ?,
           n_observations = ?, n_new = ?, error = ? WHERE id = ?""",
        (_ts(utcnow()), status, n_requests, n_observations, n_new, error, run_id),
    )
    conn.commit()


def set_run_archive(conn: sqlite3.Connection, run_id: int, key: str) -> None:
    conn.execute("UPDATE fetch_runs SET archive_key = ? WHERE id = ?", (key, run_id))
    conn.commit()


def run_archive_key(conn: sqlite3.Connection, run_id: int) -> str | None:
    row = conn.execute("SELECT archive_key FROM fetch_runs WHERE id = ?", (run_id,)).fetchone()
    return row["archive_key"] if row else None


def run_finished_at(conn: sqlite3.Connection, run_id: int) -> datetime | None:
    row = conn.execute("SELECT finished_at FROM fetch_runs WHERE id = ?", (run_id,)).fetchone()
    return datetime.fromisoformat(row["finished_at"]) if row and row["finished_at"] else None


def latest_completed_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        """SELECT id FROM fetch_runs WHERE status IN ('ok', 'partial') AND scope = 'full'
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    return row["id"] if row else None


# --- observations -------------------------------------------------------------

@dataclass(frozen=True)
class Stored:
    new: int        # offers stored for the first time
    repeated: int   # offers already stored (seen again: last_seen_at, seen_count updated)


def insert_observations(conn: sqlite3.Connection, run_id: int,
                        observations: list[Observation]) -> Stored:
    """Store each offer once (by `dedup_key`). A repeat keeps its first run and first
    fetched_at and gets `last_seen_at`, `last_run_id` and `seen_count` (once per run) updated."""
    new = 0
    for o in observations:
        seen = _ts(o.fetched_at)
        inserted = conn.execute(
            """INSERT INTO price_observations (
                   run_id, last_run_id, source, origin, destination, origin_airport,
                   destination_airport, departure_date, return_date, nights, price, currency,
                   airline, flight_number, transfers, return_transfers, deep_link, fetched_at,
                   last_seen_at, found_date, departure_at, return_at, dedup_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (dedup_key) DO NOTHING""",
            (run_id, run_id, o.source, o.origin, o.destination, o.origin_airport,
             o.destination_airport, o.departure_date.isoformat(), o.return_date.isoformat(),
             o.nights, o.price, o.currency, o.airline, o.flight_number, o.transfers,
             o.return_transfers, o.deep_link, seen, seen,
             o.found_date.isoformat() if o.found_date else None, o.departure_at, o.return_at,
             o.dedup_key),
        ).rowcount
        if inserted:
            new += 1
            continue
        conn.execute(
            """UPDATE price_observations SET
                   last_seen_at = MAX(last_seen_at, ?),
                   seen_count = seen_count + (last_run_id < ?),
                   last_run_id = MAX(last_run_id, ?)
               WHERE dedup_key = ?""",
            (seen, run_id, run_id, o.dedup_key))
    conn.commit()
    return Stored(new=new, repeated=len(observations) - new)


def _row_to_observation(row: sqlite3.Row) -> Observation:
    return Observation(
        id=row["id"], run_id=row["run_id"], source=row["source"],
        origin=row["origin"], destination=row["destination"],
        origin_airport=row["origin_airport"], destination_airport=row["destination_airport"],
        departure_date=date.fromisoformat(row["departure_date"]),
        return_date=date.fromisoformat(row["return_date"]),
        price=float(row["price"]), currency=row["currency"], airline=row["airline"],
        flight_number=row["flight_number"], transfers=row["transfers"],
        return_transfers=row["return_transfers"], deep_link=row["deep_link"],
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        found_date=date.fromisoformat(row["found_date"]) if row["found_date"] else None,
        departure_at=row["departure_at"], return_at=row["return_at"],
        last_seen_at=_dt(row["last_seen_at"]), last_run_id=row["last_run_id"],
        seen_count=row["seen_count"],
    )


def observations_seen_since(conn: sqlite3.Connection, run_id: int) -> list[Observation]:
    """Offers returned by this run or a later one (a live check, say).

    With deduplication an offer is one row whose `last_run_id` moves forward, so "the
    prices of the latest run" are the rows last seen in that run or after it.
    """
    rows = conn.execute(
        "SELECT * FROM price_observations WHERE last_run_id >= ? ORDER BY origin, destination, price",
        (run_id,),
    )
    return [_row_to_observation(r) for r in rows]


def route_history(conn: sqlite3.Connection, origin: str, destination: str, *,
                  since: datetime, exclude_run_id: int | None) -> list[Observation]:
    rows = conn.execute(
        """SELECT * FROM price_observations
           WHERE origin = ? AND destination = ? AND fetched_at >= ? AND run_id IS NOT ?
           ORDER BY fetched_at""",
        (origin, destination, _ts(since), exclude_run_id),
    )
    return [_row_to_observation(r) for r in rows]


def deal_observation_ids(conn: sqlite3.Connection) -> set[int]:
    """Observations that already became a deal (any status): never flagged twice."""
    return {r[0] for r in conn.execute("SELECT observation_id FROM deals")}


def observation_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Stored offers per route key ('LIS-LON')."""
    rows = conn.execute("SELECT origin, destination, COUNT(*) AS n FROM price_observations "
                        "GROUP BY origin, destination")
    return {f"{r['origin']}-{r['destination']}": r["n"] for r in rows}


def trip_observation_at(conn: sqlite3.Connection, o: Observation,
                        price: float) -> Observation | None:
    """The newest stored observation of `o`'s trip (route, dates) at `price`, if any."""
    row = conn.execute(
        """SELECT * FROM price_observations WHERE origin = ? AND destination = ?
           AND departure_date = ? AND return_date = ? AND price = ? ORDER BY id DESC LIMIT 1""",
        (o.origin, o.destination, o.departure_date.isoformat(), o.return_date.isoformat(),
         price)).fetchone()
    return _row_to_observation(row) if row else None


def get_observation(conn: sqlite3.Connection, observation_id: int) -> Observation:
    row = conn.execute("SELECT * FROM price_observations WHERE id = ?", (observation_id,)).fetchone()
    if row is None:
        raise KeyError(f"Observation {observation_id} not found")
    return _row_to_observation(row)


# --- deals --------------------------------------------------------------------

def recently_flagged_offers(conn: sqlite3.Connection, origin: str, destination: str,
                            since: datetime) -> list[Observation]:
    rows = conn.execute(
        """SELECT o.* FROM deals d JOIN price_observations o ON o.id = d.observation_id
           WHERE o.origin = ? AND o.destination = ? AND d.detected_at >= ?
             AND d.status != 'expired'""",
        (origin, destination, _ts(since)),
    )
    return [_row_to_observation(r) for r in rows]


def insert_deal(conn: sqlite3.Connection, *, observation_id: int, rule: str,
                baseline_median: float | None, sample_size: int, discount_pct: float | None,
                threshold: float) -> int:
    cur = conn.execute(
        """INSERT INTO deals (observation_id, rule, baseline_median, sample_size,
                              discount_pct, threshold, detected_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (observation_id, rule, baseline_median, sample_size, discount_pct, threshold,
         _ts(utcnow())),
    )
    conn.commit()
    return cur.lastrowid


def _row_to_deal(row: sqlite3.Row) -> Deal:
    return Deal(
        id=row["id"], observation_id=row["observation_id"], rule=row["rule"],
        baseline_median=None if row["baseline_median"] is None else float(row["baseline_median"]),
        sample_size=row["sample_size"],
        discount_pct=None if row["discount_pct"] is None else float(row["discount_pct"]),
        threshold=float(row["threshold"]),
        detected_at=datetime.fromisoformat(row["detected_at"]), status=row["status"],
        affiliate_url=row["affiliate_url"], affiliate_error=row["affiliate_error"],
        last_checked_at=(datetime.fromisoformat(row["last_checked_at"])
                         if row["last_checked_at"] else None),
        last_seen_price=None if row["last_seen_price"] is None else float(row["last_seen_price"]),
        expired_reason=row["expired_reason"],
        output_path=row["output_path"],
        reviewed_at=_dt(row["reviewed_at"]), review_note=row["review_note"],
        published_at=_dt(row["published_at"]), post_url=row["post_url"],
    )


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def deals_with_status(conn: sqlite3.Connection, *statuses: str) -> list[tuple[Deal, Observation]]:
    rows = conn.execute(
        f"SELECT * FROM deals WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY id DESC",
        statuses).fetchall()
    return [(_row_to_deal(r), get_observation(conn, r["observation_id"])) for r in rows]


def deal_states(conn: sqlite3.Connection) -> list[tuple[int, str, bool]]:
    """(id, status, has a tracked link) for every deal: what the fast/full decision watches."""
    rows = conn.execute("SELECT id, status, affiliate_url IS NOT NULL AS linked FROM deals "
                        "ORDER BY id").fetchall()
    return [(r["id"], r["status"], bool(r["linked"])) for r in rows]


def fixture_mark_live(conn: sqlite3.Connection, deal_id: int) -> None:
    """Fixture generation only, on an in-memory copy (D27): the deal as if approved when it
    was detected. Real review decisions go through `settle_review_event` (D26)."""
    conn.execute("""UPDATE deals SET status = 'approved', reviewed_at = detected_at,
                    expired_reason = NULL WHERE id = ?""", (deal_id,))
    conn.commit()


def fixture_mark_reviewed(conn: sqlite3.Connection, deal_id: int) -> None:
    """Fixture generation only, on an in-memory copy (D27): an expired deal as if a human had
    approved it before it expired."""
    conn.execute("UPDATE deals SET reviewed_at = detected_at WHERE id = ?", (deal_id,))
    conn.commit()


def deals_with_output(conn: sqlite3.Connection) -> list[Deal]:
    rows = conn.execute("SELECT * FROM deals WHERE output_path IS NOT NULL ORDER BY id").fetchall()
    return [_row_to_deal(r) for r in rows]


def set_deal_output_path(conn: sqlite3.Connection, deal_id: int, path: str) -> None:
    conn.execute("UPDATE deals SET output_path = ? WHERE id = ?", (path, deal_id))
    conn.commit()


def _review_update(conn: sqlite3.Connection, deal_id: int, status: str, *, note: str | None,
                   post_url: str | None, at: datetime) -> None:
    if status == "published":
        conn.execute("UPDATE deals SET status = 'published', published_at = ?, post_url = ? "
                     "WHERE id = ?", (_ts(at), post_url, deal_id))
    else:
        conn.execute("UPDATE deals SET status = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
                     (status, _ts(at), note, deal_id))


def record_review(conn: sqlite3.Connection, deal_id: int, *, status: str,
                  note: str | None) -> None:
    """Test setup only: the pipeline changes review statuses through `settle_review_event`."""
    _review_update(conn, deal_id, status, note=note, post_url=None, at=utcnow())
    conn.commit()


REVIEW_EVENT_KEY = "review_event:"   # meta key prefix: outcome of each applied review event (D26)


def settle_review_event(conn: sqlite3.Connection, event_id: str, outcome: dict, *,
                        deal_id: int | None = None, status: str | None = None,
                        note: str | None = None, post_url: str | None = None,
                        at: datetime | None = None,
                        posts: list[tuple[str, datetime]] = (),
                        checked_at: datetime | None = None) -> None:
    """Record a review event's outcome and, when it was applied, the deal's new status, in one
    transaction: the database alone tells whether an event was already applied. `posts`:
    (channel, due_at) rows an applied approval queues (D32), written in the same transaction
    with the approval's live-check time `checked_at`."""
    with conn:
        if status is not None:
            _review_update(conn, deal_id, status, note=note, post_url=post_url, at=at or utcnow())
            conn.executemany(
                """INSERT INTO posting_queue (deal_id, channel, due_at, created_at, event_id,
                                             checked_at)
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (deal_id, channel) DO NOTHING""",
                [(deal_id, channel, _ts(due), _ts(utcnow()), event_id,
                  _ts(checked_at) if checked_at else None)
                 for channel, due in posts])
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
                     (REVIEW_EVENT_KEY + event_id, json.dumps(outcome, ensure_ascii=False)))


def review_event_outcome(conn: sqlite3.Connection, event_id: str) -> dict | None:
    value = get_meta(conn, REVIEW_EVENT_KEY + event_id)
    return json.loads(value) if value else None


def review_event_outcomes(conn: sqlite3.Connection) -> list[dict]:
    """Every recorded outcome, newest first."""
    rows = conn.execute("SELECT value FROM meta WHERE key LIKE ?", (REVIEW_EVENT_KEY + "%",))
    return sorted((json.loads(r["value"]) for r in rows), key=lambda o: o["settled_at"],
                  reverse=True)


def get_deal(conn: sqlite3.Connection, deal_id: int) -> tuple[Deal, Observation]:
    row = conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if row is None:
        raise KeyError(f"Deal {deal_id} not found")
    return _row_to_deal(row), get_observation(conn, row["observation_id"])


def set_deal_affiliate(conn: sqlite3.Connection, deal_id: int, url: str | None,
                       error: str | None) -> None:
    conn.execute("UPDATE deals SET affiliate_url = ?, affiliate_error = ? WHERE id = ?",
                 (url, error, deal_id))
    conn.commit()


OPEN_STATUSES = ("new", "rendered", "approved")


def open_deals(conn: sqlite3.Connection) -> list[tuple[Deal, Observation]]:
    """Deals that could still be published, so they must be rechecked."""
    rows = conn.execute(
        f"SELECT * FROM deals WHERE status IN ({','.join('?' * len(OPEN_STATUSES))}) ORDER BY id",
        OPEN_STATUSES).fetchall()
    return [(_row_to_deal(r), get_observation(conn, r["observation_id"])) for r in rows]


def record_recheck(conn: sqlite3.Connection, deal_id: int, *, valid: bool,
                   latest_price: float | None, reason: str,
                   at: datetime | None = None) -> None:
    conn.execute(
        """UPDATE deals SET last_checked_at = ?, last_seen_price = ?,
               status = CASE WHEN ? THEN status ELSE 'expired' END,
               expired_reason = CASE WHEN ? THEN NULL ELSE ? END
           WHERE id = ?""",
        (_ts(at or utcnow()), latest_price, valid, valid, reason, deal_id))
    conn.commit()


def set_deal_status(conn: sqlite3.Connection, deal_id: int, status: str) -> None:
    conn.execute("UPDATE deals SET status = ? WHERE id = ?", (status, deal_id))
    conn.commit()


# --- posting queue (D32) -------------------------------------------------------------

def _row_to_post(row: sqlite3.Row) -> Post:
    return Post(
        id=row["id"], deal_id=row["deal_id"], channel=row["channel"],
        due_at=datetime.fromisoformat(row["due_at"]), status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]), event_id=row["event_id"],
        checked_at=_dt(row["checked_at"]), attempts=row["attempts"], last_error=row["last_error"], publisher=row["publisher"],
        result_url=row["result_url"], reason=row["reason"], settled_at=_dt(row["settled_at"]))


def posts(conn: sqlite3.Connection, *statuses: str) -> list[Post]:
    """Queue rows (all, or with these statuses), by due time."""
    where = f"WHERE status IN ({','.join('?' * len(statuses))})" if statuses else ""
    rows = conn.execute(f"SELECT * FROM posting_queue {where} ORDER BY due_at, id", statuses)
    return [_row_to_post(r) for r in rows]


def get_post(conn: sqlite3.Connection, post_id: int) -> Post:
    return _row_to_post(conn.execute("SELECT * FROM posting_queue WHERE id = ?",
                                     (post_id,)).fetchone())


def post_due_times(conn: sqlite3.Connection, channel: str) -> list[datetime]:
    """Due times held on `channel`: queued and published posts (a cancelled one frees its slot)."""
    rows = conn.execute("SELECT due_at FROM posting_queue WHERE channel = ? "
                        "AND status IN ('queued', 'published')", (channel,))
    return [datetime.fromisoformat(r["due_at"]) for r in rows]


def settle_post(conn: sqlite3.Connection, post_id: int, status: str, *, at: datetime,
                publisher: str | None = None, result_url: str | None = None,
                reason: str | None = None) -> None:
    """A queued post published or cancelled (final)."""
    conn.execute("""UPDATE posting_queue SET status = ?, settled_at = ?, publisher = ?,
                    result_url = ?, reason = ? WHERE id = ? AND status = 'queued'""",
                 (status, _ts(at), publisher, result_url, reason, post_id))
    conn.commit()


def post_waits(conn: sqlite3.Connection, post_id: int, why: str, *, failed: bool) -> int:
    """A queued post stays queued: `why` it waits; a publisher error (`failed`) also counts an
    attempt. Returns the attempts so far."""
    conn.execute("UPDATE posting_queue SET last_error = ?, attempts = attempts + ? WHERE id = ?",
                 (why, int(failed), post_id))
    conn.commit()
    return conn.execute("SELECT attempts FROM posting_queue WHERE id = ?",
                        (post_id,)).fetchone()["attempts"]


# --- photos -------------------------------------------------------------------

def get_photo(conn: sqlite3.Connection, destination: str) -> Photo | None:
    row = conn.execute("SELECT * FROM photos WHERE destination = ?", (destination,)).fetchone()
    if row is None:
        return None
    return Photo(**{k: row[k] for k in row.keys() if k != "fetched_at"},
                 fetched_at=datetime.fromisoformat(row["fetched_at"]))


def upsert_photo(conn: sqlite3.Connection, photo: Photo) -> None:
    conn.execute(
        """INSERT INTO photos (destination, file_path, source, source_url, photographer,
                               photographer_url, license, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(destination) DO UPDATE SET
               file_path = excluded.file_path, source = excluded.source,
               source_url = excluded.source_url, photographer = excluded.photographer,
               photographer_url = excluded.photographer_url, license = excluded.license,
               fetched_at = excluded.fetched_at""",
        (photo.destination, photo.file_path, photo.source, photo.source_url, photo.photographer,
         photo.photographer_url, photo.license, _ts(photo.fetched_at)),
    )
    conn.commit()


# --- routes -------------------------------------------------------------------

ROUTE_OVERRIDES = ("direct_only", "min_nights", "max_nights", "max_transfers", "price_cap_eur")


def route_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All routes in the order they were added."""
    return conn.execute("SELECT * FROM routes ORDER BY rowid").fetchall()


def insert_route(conn: sqlite3.Connection, *, origin: str, destination: str, city_pt: str,
                 kind: str, discovered_at: datetime, city_en: str | None = None,
                 destination_airports: str | None = None) -> bool:
    """Add a route unless it exists. Backfills last_observed_at from stored prices."""
    cur = conn.execute(
        """INSERT INTO routes (origin, destination, city_pt, city_en, kind, destination_airports,
                               discovered_at, last_observed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, (SELECT MAX(last_seen_at) FROM price_observations
                                         WHERE origin = ? AND destination = ?))
           ON CONFLICT (origin, destination) DO NOTHING""",
        (origin, destination, city_pt, city_en, kind, destination_airports, _ts(discovered_at),
         origin, destination))
    conn.commit()
    return cur.rowcount == 1


def set_route_catalogue(conn: sqlite3.Connection, origin: str, destination: str, *,
                        city_en: str | None, destination_airports: str | None) -> None:
    """Refresh what discovery knows about a stored route (never its name, kind or rules)."""
    conn.execute(
        """UPDATE routes SET city_en = COALESCE(?, city_en),
                             destination_airports = COALESCE(?, destination_airports)
           WHERE origin = ? AND destination = ?""",
        (city_en, destination_airports, origin, destination))
    conn.commit()


def set_route_status(conn: sqlite3.Connection, keys: list[tuple[str, str]], status: str) -> None:
    conn.executemany("UPDATE routes SET status = ? WHERE origin = ? AND destination = ?",
                     [(status, o, d) for o, d in keys])
    conn.commit()


def set_city_name(conn: sqlite3.Connection, destination: str, city_pt: str) -> None:
    conn.execute("UPDATE routes SET city_pt = ? WHERE destination = ?", (city_pt, destination))
    conn.commit()


def set_route_overrides(conn: sqlite3.Connection, origin: str, destination: str,
                        overrides: dict) -> None:
    """Replace the override columns (missing keys become NULL = kind default)."""
    conn.execute(
        f"UPDATE routes SET {', '.join(f'{c} = ?' for c in ROUTE_OVERRIDES)} "
        "WHERE origin = ? AND destination = ?",
        (*(overrides.get(c) for c in ROUTE_OVERRIDES), origin, destination))
    conn.commit()


def touch_routes_observed(conn: sqlite3.Connection, run_id: int) -> None:
    """last_observed_at = newest sighting of a price, for every route that got prices in this run.

    A sighting, not a first sighting: the cache returns the same offers for days, and a route
    whose offers keep coming back is observed (`last_seen_at`, not `fetched_at`; D18).
    """
    conn.execute(
        """UPDATE routes SET last_observed_at = (
               SELECT MAX(last_seen_at) FROM price_observations p
               WHERE p.origin = routes.origin AND p.destination = routes.destination)
           WHERE EXISTS (SELECT 1 FROM price_observations p WHERE p.last_run_id = ?
                         AND p.origin = routes.origin AND p.destination = routes.destination)""",
        (run_id,))
    conn.commit()


# --- meta (pipeline bookkeeping) -------------------------------------------------

def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def get_meta_json(conn: sqlite3.Connection, key: str) -> dict:
    """A JSON object stored under `key`, {} when there is none."""
    return json.loads(get_meta(conn, key) or "{}")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()


# --- partner links (low prices on the website) -------------------------------------

def partner_links(conn: sqlite3.Connection, project_id: int,
                  observation_ids: list[int]) -> dict[int, tuple[str | None, str | None]]:
    """observation id -> (partner_url, error) already stored for this Project."""
    out: dict[int, tuple[str | None, str | None]] = {}
    ids = list(dict.fromkeys(observation_ids))
    for start in range(0, len(ids), 500):            # SQLite's bound-parameter limit
        chunk = ids[start:start + 500]
        rows = conn.execute(
            f"""SELECT observation_id, partner_url, error FROM partner_links
                WHERE project_id = ? AND observation_id IN ({','.join('?' * len(chunk))})""",
            (project_id, *chunk))
        out |= {r["observation_id"]: (r["partner_url"], r["error"]) for r in rows}
    return out


def save_partner_links(conn: sqlite3.Connection, project_id: int,
                       links: dict[int, tuple[str | None, str | None]]) -> None:
    """Store each attempt; a later success replaces an earlier failure."""
    now = _ts(utcnow())
    conn.executemany(
        """INSERT INTO partner_links (observation_id, project_id, partner_url, error, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (observation_id, project_id) DO UPDATE SET
               partner_url = excluded.partner_url, error = excluded.error,
               created_at = excluded.created_at""",
        [(oid, project_id, url, error, now) for oid, (url, error) in links.items()])
    conn.commit()


def prune_partner_links(conn: sqlite3.Connection, before: datetime) -> int:
    """Forget links created before `before`: their offers are long past the freshness window."""
    n = conn.execute("DELETE FROM partner_links WHERE created_at < ?", (_ts(before),)).rowcount
    conn.commit()
    return n


# --- stats --------------------------------------------------------------------

def route_stats(conn: sqlite3.Connection, origin: str, destination: str) -> sqlite3.Row:
    return conn.execute(
        """SELECT COUNT(*) AS n, MIN(price) AS min_price, MAX(price) AS max_price,
                  MIN(fetched_at) AS first_seen, MAX(last_seen_at) AS last_seen,
                  COUNT(DISTINCT run_id) AS runs, SUM(seen_count) AS sightings,
                  MAX(seen_count) AS max_seen
           FROM price_observations WHERE origin = ? AND destination = ?""",
        (origin, destination),
    ).fetchone()


# --- migration 7: deduplicate observations, move raw payloads out --------------------

OBSERVATIONS_V7 = """CREATE TABLE price_observations_v7 (
    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES fetch_runs(id),
    last_run_id INTEGER NOT NULL REFERENCES fetch_runs(id), source TEXT NOT NULL,
    origin TEXT NOT NULL, destination TEXT NOT NULL, origin_airport TEXT,
    destination_airport TEXT, departure_date TEXT NOT NULL, return_date TEXT NOT NULL,
    nights INTEGER NOT NULL, price NUMERIC NOT NULL CHECK (price > 0), currency TEXT NOT NULL,
    airline TEXT, flight_number TEXT, transfers INTEGER, return_transfers INTEGER,
    deep_link TEXT, fetched_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1, found_date TEXT, departure_at TEXT, return_at TEXT,
    dedup_key TEXT NOT NULL UNIQUE)"""

_V7_COLUMNS = ("id", "run_id", "last_run_id", "source", "origin", "destination", "origin_airport",
               "destination_airport", "departure_date", "return_date", "nights", "price",
               "currency", "airline", "flight_number", "transfers", "return_transfers",
               "deep_link", "fetched_at", "last_seen_at", "seen_count", "found_date",
               "departure_at", "return_at", "dedup_key")


def _legacy_key(row: sqlite3.Row, raw: dict) -> str:
    return Observation(
        source=row["source"], origin=row["origin"], destination=row["destination"],
        origin_airport=None, destination_airport=None,
        departure_date=date.fromisoformat(row["departure_date"]),
        return_date=date.fromisoformat(row["return_date"]), price=float(row["price"]),
        currency=row["currency"], airline=row["airline"], flight_number=row["flight_number"],
        transfers=None, return_transfers=None, deep_link=None,
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        found_date=date.fromisoformat(row["found_date"]) if row["found_date"] else None,
        departure_at=raw.get("departure_at"), return_at=raw.get("return_at"),
    ).dedup_key


def _dedupe_observations(conn: sqlite3.Connection) -> None:
    """Collapse identical offers into one row and park every raw payload in `raw_pending`,
    which archive.flush_legacy moves to the object store. A row with a deal keeps its id."""
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")     # the table is rebuilt under deals' feet
    conn.execute(OBSERVATIONS_V7)
    conn.execute("""CREATE TABLE raw_pending (
                        run_id INTEGER NOT NULL, observation_id INTEGER NOT NULL,
                        origin TEXT NOT NULL, destination TEXT NOT NULL, raw_json TEXT NOT NULL)""")
    with_deal = {r[0] for r in conn.execute("SELECT observation_id FROM deals")}
    groups: dict[str, list[tuple[sqlite3.Row, dict]]] = {}
    for row in conn.execute("SELECT * FROM price_observations ORDER BY id"):
        raw = json.loads(row["raw_json"] or "{}")
        groups.setdefault(_legacy_key(row, raw), []).append((row, raw))

    for key, members in groups.items():
        rows = [r for r, _ in members]
        dealt = [r for r in rows if r["id"] in with_deal]
        # Normally one row per offer. Two deals on the same offer (never observed) would
        # both be kept, the second under a suffixed key, so no deal loses its observation.
        keep = [dealt[0] if dealt else rows[0], *dealt[1:]]
        for i, row in enumerate(keep):
            merged = rows if i == 0 else [row]
            new = dict(row)
            new.update(
                run_id=min(r["run_id"] for r in merged),
                last_run_id=max(r["run_id"] for r in merged),
                fetched_at=min(r["fetched_at"] for r in merged),
                last_seen_at=max(r["fetched_at"] for r in merged),
                seen_count=len({r["run_id"] for r in merged}),
                departure_at=members[0][1].get("departure_at"),
                return_at=members[0][1].get("return_at"),
                dedup_key=key if i == 0 else f"{key}#legacy-{row['id']}")
            conn.execute(f"INSERT INTO price_observations_v7 ({', '.join(_V7_COLUMNS)}) "
                         f"VALUES ({', '.join('?' * len(_V7_COLUMNS))})",
                         [new[c] for c in _V7_COLUMNS])
        conn.executemany(
            "INSERT INTO raw_pending VALUES (?, ?, ?, ?, ?)",
            [(r["run_id"], keep[0]["id"], r["origin"], r["destination"], r["raw_json"])
             for r in rows])

    conn.execute("DROP TABLE price_observations")
    conn.execute("ALTER TABLE price_observations_v7 RENAME TO price_observations")
    conn.execute("CREATE INDEX ix_obs_route_time ON price_observations (origin, destination, fetched_at)")
    conn.execute("CREATE INDEX ix_obs_last_run ON price_observations (last_run_id)")
    conn.execute("ALTER TABLE fetch_runs ADD COLUMN n_new INTEGER")
    conn.execute("ALTER TABLE fetch_runs ADD COLUMN archive_key TEXT")
    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
    if broken:
        conn.rollback()
        raise RuntimeError(f"Migration 7 would break references: {[tuple(b) for b in broken][:5]}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


MIGRATIONS[7] = [_dedupe_observations]


def raw_pending_exists(conn: sqlite3.Connection) -> bool:
    """True until the payloads parked by migration 7 are archived."""
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'raw_pending'").fetchone() is not None


def raw_pending_runs(conn: sqlite3.Connection) -> list[int]:
    """Runs whose raw payloads still wait in `raw_pending`."""
    return [r[0] for r in conn.execute("SELECT DISTINCT run_id FROM raw_pending ORDER BY run_id")]


def raw_pending_items(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM raw_pending WHERE run_id = ? ORDER BY rowid",
                        (run_id,)).fetchall()


def drop_raw_pending(conn: sqlite3.Connection, run_id: int) -> None:
    conn.execute("DELETE FROM raw_pending WHERE run_id = ?", (run_id,))
    conn.commit()


def finish_raw_pending(conn: sqlite3.Connection) -> None:
    """All payloads archived: drop the table and give the space back."""
    conn.execute("DROP TABLE IF EXISTS raw_pending")
    conn.commit()
    conn.execute("VACUUM")

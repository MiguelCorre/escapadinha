"""SQLite access: plain SQL, one function per query. No ORM."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path

from escapadinha.models import Deal, Observation, Photo

SCHEMA_VERSION = 2

# Steps that bring an existing database from version N-1 to N.
MIGRATIONS = {
    2: ["ALTER TABLE price_observations ADD COLUMN found_date TEXT"],
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


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
            for statement in MIGRATIONS[version]:
                conn.execute(statement)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


# --- fetch runs -------------------------------------------------------------

def start_run(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO fetch_runs (source, started_at) VALUES (?, ?)", (source, _ts(utcnow()))
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, *, status: str, n_requests: int,
               n_observations: int, error: str | None) -> None:
    conn.execute(
        """UPDATE fetch_runs SET finished_at = ?, status = ?, n_requests = ?,
           n_observations = ?, error = ? WHERE id = ?""",
        (_ts(utcnow()), status, n_requests, n_observations, error, run_id),
    )
    conn.commit()


def latest_completed_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM fetch_runs WHERE status IN ('ok', 'partial') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


# --- observations -------------------------------------------------------------

def insert_observations(conn: sqlite3.Connection, run_id: int, observations: list[Observation]) -> int:
    conn.executemany(
        """INSERT INTO price_observations (
               run_id, source, origin, destination, origin_airport, destination_airport,
               departure_date, return_date, nights, price, currency, airline, flight_number,
               transfers, return_transfers, deep_link, fetched_at, found_date, raw_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (run_id, o.source, o.origin, o.destination, o.origin_airport, o.destination_airport,
             o.departure_date.isoformat(), o.return_date.isoformat(), o.nights, o.price,
             o.currency, o.airline, o.flight_number, o.transfers, o.return_transfers,
             o.deep_link, _ts(o.fetched_at),
             o.found_date.isoformat() if o.found_date else None, o.raw_json)
            for o in observations
        ],
    )
    conn.commit()
    return len(observations)


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
        fetched_at=datetime.fromisoformat(row["fetched_at"]), raw_json=row["raw_json"],
        found_date=date.fromisoformat(row["found_date"]) if row["found_date"] else None,
    )


def observations_for_run(conn: sqlite3.Connection, run_id: int) -> list[Observation]:
    rows = conn.execute(
        "SELECT * FROM price_observations WHERE run_id = ? ORDER BY origin, destination, price",
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
           WHERE o.origin = ? AND o.destination = ? AND d.detected_at >= ?""",
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
    )


def deals_with_status(conn: sqlite3.Connection, status: str) -> list[tuple[Deal, Observation]]:
    rows = conn.execute("SELECT * FROM deals WHERE status = ? ORDER BY id", (status,)).fetchall()
    return [(_row_to_deal(r), get_observation(conn, r["observation_id"])) for r in rows]


def get_deal(conn: sqlite3.Connection, deal_id: int) -> tuple[Deal, Observation]:
    row = conn.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
    if row is None:
        raise KeyError(f"Deal {deal_id} not found")
    return _row_to_deal(row), get_observation(conn, row["observation_id"])


def set_deal_status(conn: sqlite3.Connection, deal_id: int, status: str) -> None:
    conn.execute("UPDATE deals SET status = ? WHERE id = ?", (status, deal_id))
    conn.commit()


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


# --- stats --------------------------------------------------------------------

def route_stats(conn: sqlite3.Connection, origin: str, destination: str) -> sqlite3.Row:
    return conn.execute(
        """SELECT COUNT(*) AS n, MIN(price) AS min_price, MAX(price) AS max_price,
                  MIN(fetched_at) AS first_seen, MAX(fetched_at) AS last_seen,
                  COUNT(DISTINCT run_id) AS runs
           FROM price_observations WHERE origin = ? AND destination = ?""",
        (origin, destination),
    ).fetchone()

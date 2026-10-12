-- Schema version 2 (fresh installs). Older databases are migrated in db.py. Timestamps are UTC ISO-8601 strings, dates are YYYY-MM-DD.

CREATE TABLE IF NOT EXISTS fetch_runs (
    id             INTEGER PRIMARY KEY,
    source         TEXT    NOT NULL,
    started_at     TEXT    NOT NULL,
    finished_at    TEXT,
    status         TEXT    NOT NULL DEFAULT 'running',  -- running | ok | partial | failed
    n_requests     INTEGER NOT NULL DEFAULT 0,
    n_observations INTEGER NOT NULL DEFAULT 0,
    error          TEXT
);

CREATE TABLE IF NOT EXISTS price_observations (
    id                  INTEGER PRIMARY KEY,
    run_id              INTEGER NOT NULL REFERENCES fetch_runs(id),
    source              TEXT    NOT NULL,
    origin              TEXT    NOT NULL,
    destination         TEXT    NOT NULL,
    origin_airport      TEXT,
    destination_airport TEXT,
    departure_date      TEXT    NOT NULL,
    return_date         TEXT    NOT NULL,
    nights              INTEGER NOT NULL,
    price               NUMERIC NOT NULL CHECK (price > 0),
    currency            TEXT    NOT NULL,
    airline             TEXT,
    flight_number       TEXT,
    transfers           INTEGER,
    return_transfers    INTEGER,
    deep_link           TEXT,
    fetched_at          TEXT    NOT NULL,
    found_date          TEXT,               -- day a user found the price (source cache)
    raw_json            TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_obs_route_time
    ON price_observations (origin, destination, fetched_at);

CREATE TABLE IF NOT EXISTS deals (
    id              INTEGER PRIMARY KEY,
    observation_id  INTEGER NOT NULL UNIQUE REFERENCES price_observations(id),
    rule            TEXT    NOT NULL CHECK (rule IN ('median', 'price_cap')),
    baseline_median NUMERIC,
    sample_size     INTEGER NOT NULL,
    discount_pct    NUMERIC,
    threshold       NUMERIC NOT NULL,
    detected_at     TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'rendered', 'approved', 'rejected', 'published'))
);

CREATE TABLE IF NOT EXISTS photos (
    destination      TEXT PRIMARY KEY,
    file_path        TEXT NOT NULL,
    source           TEXT NOT NULL,
    source_url       TEXT NOT NULL,
    photographer     TEXT NOT NULL,
    photographer_url TEXT NOT NULL,
    license          TEXT NOT NULL,
    fetched_at       TEXT NOT NULL
);

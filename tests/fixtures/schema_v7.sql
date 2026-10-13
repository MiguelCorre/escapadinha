-- Schema version 7 (fresh installs). Older databases are migrated in db.py. Timestamps are UTC ISO-8601 strings, dates are YYYY-MM-DD.

CREATE TABLE IF NOT EXISTS fetch_runs (
    id             INTEGER PRIMARY KEY,
    source         TEXT    NOT NULL,
    started_at     TEXT    NOT NULL,
    finished_at    TEXT,
    status         TEXT    NOT NULL DEFAULT 'running',  -- running | ok | partial | failed
    scope          TEXT    NOT NULL DEFAULT 'full',     -- full (all routes) | live_check (one deal)
    n_requests     INTEGER NOT NULL DEFAULT 0,
    n_observations INTEGER NOT NULL DEFAULT 0,     -- offers returned by the source
    n_new          INTEGER,                        -- of those, not stored before
    error          TEXT,
    archive_key    TEXT                            -- object store key of the raw responses
);

-- One row per distinct offer (dedup_key = source, route, departure/return timestamps,
-- airline, flight number, price, found date). Raw API responses live in the run archive.
CREATE TABLE IF NOT EXISTS price_observations (
    id                  INTEGER PRIMARY KEY,
    run_id              INTEGER NOT NULL REFERENCES fetch_runs(id),   -- first run that saw it
    last_run_id         INTEGER NOT NULL REFERENCES fetch_runs(id),
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
    fetched_at          TEXT    NOT NULL,   -- first time we saw it
    last_seen_at        TEXT    NOT NULL,
    seen_count          INTEGER NOT NULL DEFAULT 1,   -- runs that returned it
    found_date          TEXT,               -- day a user found the price (source cache)
    departure_at        TEXT,               -- source timestamps (UTC)
    return_at           TEXT,
    dedup_key           TEXT    NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS ix_obs_route_time
    ON price_observations (origin, destination, fetched_at);
CREATE INDEX IF NOT EXISTS ix_obs_last_run ON price_observations (last_run_id);

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
        CHECK (status IN ('new', 'rendered', 'approved', 'rejected', 'published', 'expired')),
    affiliate_url   TEXT,
    affiliate_error TEXT,
    last_checked_at TEXT,      -- last recheck against a newer collection run
    last_seen_price NUMERIC,   -- cheapest price for the same trip at that recheck
    expired_reason  TEXT,
    output_path     TEXT,      -- folder with slides/caption/meta from the last render
    reviewed_at     TEXT,      -- approve/reject time
    review_note     TEXT,
    published_at    TEXT,
    post_url        TEXT
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

CREATE TABLE IF NOT EXISTS routes (
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
);

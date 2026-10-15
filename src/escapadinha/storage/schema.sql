-- Schema version 13 (fresh installs). Older databases are migrated in db.py. Timestamps are UTC ISO-8601 strings, dates are YYYY-MM-DD.

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
    post_url        TEXT,
    -- The typical low behind the deal, shown to the reviewer (D40): first to last baseline
    -- day, and the observations that are its cheapest and dearest daily low.
    baseline_span_days      INTEGER,
    baseline_lowest_obs_id  INTEGER REFERENCES price_observations(id),
    baseline_highest_obs_id INTEGER REFERENCES price_observations(id)
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
    last_observed_at     TEXT,                       -- newest sighting of a price on this route
    city_en              TEXT,                       -- English name (photo search), from discovery
    PRIMARY KEY (origin, destination)
);

-- Pipeline bookkeeping, e.g. `routes.discovered_at` (last automatic route discovery).
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Tracked links per (observation, Travelpayouts Project) for low prices on the website (D24),
-- created once through the partner links API.
CREATE TABLE IF NOT EXISTS partner_links (
    observation_id INTEGER NOT NULL REFERENCES price_observations(id),
    project_id     INTEGER NOT NULL,             -- Travelpayouts Project ("trs")
    partner_url    TEXT,                         -- NULL when the conversion failed
    error          TEXT,
    created_at     TEXT NOT NULL,                -- UTC, last attempt
    PRIMARY KEY (observation_id, project_id)
);

-- Posting queue (D32): one row per approved promotion and channel. Instagram rows are due at a
-- daily slot (Lisbon time), Telegram rows at the approval. A run publishes due rows after
-- re-verifying the promotion; an expired or rejected promotion cancels its rows.
CREATE TABLE IF NOT EXISTS posting_queue (
    id         INTEGER PRIMARY KEY,
    deal_id    INTEGER NOT NULL REFERENCES deals(id),
    channel    TEXT    NOT NULL CHECK (channel IN ('instagram', 'telegram')),
    due_at     TEXT    NOT NULL,             -- UTC
    status     TEXT    NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'published', 'cancelled')),
    created_at TEXT    NOT NULL,
    event_id   TEXT,                         -- the approve event that queued it
    checked_at TEXT,                         -- that event's live price check (UTC)
    attempts   INTEGER NOT NULL DEFAULT 0,   -- publisher errors so far
    last_error TEXT,                         -- last publisher error, or why it waits (pt-PT)
    publisher  TEXT,                         -- who published it: 'dry-run', 'instagram', ...
    result_url TEXT,                         -- the post's URL, when the publisher has one
    reason     TEXT,                         -- why it was cancelled (pt-PT)
    settled_at TEXT,                         -- published / cancelled at
    -- Instagram publisher progress (D36, v11), so a retry never posts twice:
    container_id       TEXT,                 -- carousel container created, not published yet
    media_id           TEXT,                 -- the published carousel's media id
    story_status       TEXT CHECK (story_status IN ('pending', 'published', 'skipped')),
    story_container_id TEXT,                 -- story container created, not published yet
    story_media_id     TEXT,                 -- the published story's media id
    story_attempts     INTEGER NOT NULL DEFAULT 0,   -- story errors so far
    story_note         TEXT,                 -- last story error, why it waits or was skipped (pt-PT)
    caption            TEXT,                 -- the caption of the first attempt, reused by retries
    -- Telegram publisher (D38, v12): the channel message's id (its link is result_url).
    message_id         TEXT,
    UNIQUE (deal_id, channel)
);

CREATE INDEX IF NOT EXISTS ix_posting_due ON posting_queue (status, due_at);

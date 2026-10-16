"""Plain data records shared between collector, storage, detector and renderer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Observation:
    """One price returned by a source. Never constructed from anything but API data."""

    source: str
    origin: str
    destination: str
    origin_airport: str | None
    destination_airport: str | None
    departure_date: date
    return_date: date
    price: float
    currency: str
    airline: str | None
    flight_number: str | None
    transfers: int | None
    return_transfers: int | None
    deep_link: str | None
    fetched_at: datetime                 # first time we saw this offer
    raw_json: str = ""                   # API item; archived per run, not stored in the table
    found_date: date | None = None   # when a user found the price (source cache), if known
    run_id: int | None = None            # first run that saw it
    id: int | None = None
    departure_at: str | None = None      # source timestamps, part of the offer's identity
    return_at: str | None = None
    last_seen_at: datetime | None = None
    last_run_id: int | None = None
    seen_count: int = 1                  # number of runs that returned this offer
    # Enrichment from the Aviasales GraphQL API (D43): only ever set from a row matched to this
    # offer, never guessed; None = unknown. `found_at` is the exact UTC time a traveller found it.
    with_baggage: bool | None = None
    baggage_code: str | None = None      # "0PC" = no checked bag, "1PC20" = one 20 kg bag
    gate: str | None = None              # the selling agency
    found_at: datetime | None = None

    @property
    def nights(self) -> int:
        return (self.return_date - self.departure_date).days

    @property
    def route_key(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def dedup_key(self) -> str:
        """Identity of an offer independent of when we saw it: repeats are stored once."""
        parts = (self.source, self.origin, self.destination,
                 self.departure_at or self.departure_date.isoformat(),
                 self.return_at or self.return_date.isoformat(),
                 self.airline or "", self.flight_number or "", f"{self.price:.2f}",
                 self.found_date.isoformat() if self.found_date else "")
        return "|".join(parts)


@dataclass(frozen=True)
class RouteRules:
    """What counts as a usable offer on a route. Defaults come from the route's kind."""

    direct_only: bool = True           # nonstop both ways (overrides max_transfers)
    min_nights: int = 2
    max_nights: int = 10
    max_transfers: int | None = 0      # per direction; None = no limit

    def to_json(self) -> dict:
        """The rules as the data contracts carry them (site data, review snapshot)."""
        return {"direct_only": self.direct_only, "min_nights": self.min_nights,
                "max_nights": self.max_nights, "max_transfers": self.max_transfers}

    @property
    def nonstop_only(self) -> bool:
        """Only nonstop flights both ways count: `direct_only`, or a stop limit of 0."""
        return self.direct_only or self.max_transfers == 0

    def allows(self, o: Observation) -> bool:
        """Within the nights range and the stop limit. Unknown transfer counts never pass a limit."""
        if not self.min_nights <= o.nights <= self.max_nights:
            return False
        limit = 0 if self.direct_only else self.max_transfers
        if limit is None:
            return True
        return (o.transfers is not None and o.return_transfers is not None
                and o.transfers <= limit and o.return_transfers <= limit)


@dataclass(frozen=True)
class Route:
    """A watched origin → destination pair, independent of dates (stored in `routes`)."""

    origin: str
    destination: str                   # provider city code (e.g. LON)
    city_pt: str
    kind: str                          # europe | long_haul | domestic
    rules: RouteRules
    status: str = "active"             # active | dormant
    price_cap_eur: float | None = None
    destination_airports: str | None = None
    discovered_at: datetime | None = None
    last_observed_at: datetime | None = None
    city_en: str | None = None         # English name from the provider catalogue (photo search)

    @property
    def key(self) -> str:
        return f"{self.origin}-{self.destination}"


@dataclass(frozen=True)
class Deal:
    id: int
    observation_id: int
    rule: str
    baseline_median: float | None
    sample_size: int
    discount_pct: float | None
    threshold: float
    detected_at: datetime
    status: str
    affiliate_url: str | None = None     # tracked link from the partner links API
    affiliate_error: str | None = None   # why conversion failed, if it did
    last_checked_at: datetime | None = None
    last_seen_price: float | None = None
    expired_reason: str | None = None
    output_path: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    published_at: datetime | None = None
    post_url: str | None = None
    # The typical low behind it, for the reviewer (D40); None for deals detected before.
    baseline_span_days: int | None = None       # first to last baseline day
    baseline_lowest_obs_id: int | None = None   # observation of the cheapest daily low
    baseline_highest_obs_id: int | None = None  # observation of the dearest daily low


@dataclass(frozen=True)
class Post:
    """One promotion on one channel in the posting queue (D32)."""

    id: int
    deal_id: int
    channel: str                       # instagram | telegram
    due_at: datetime                   # UTC: an Instagram daily slot, or the approval for Telegram
    status: str                        # queued | published | cancelled
    created_at: datetime
    event_id: str | None = None        # the approve event that queued it
    checked_at: datetime | None = None  # that event's live check (`live_check.checked_at`), UTC
    attempts: int = 0                  # publisher errors so far
    last_error: str | None = None      # last publisher error, or why it is waiting (pt-PT)
    publisher: str | None = None       # who published it: 'dry-run', ...
    result_url: str | None = None      # the post's URL, when the publisher returns one
    reason: str | None = None          # why it was cancelled (pt-PT)
    settled_at: datetime | None = None
    # Instagram publisher progress (D36): what was already done, so a retry never posts twice.
    container_id: str | None = None    # carousel container created, not published yet
    media_id: str | None = None        # the published carousel
    story_status: str | None = None    # None | pending | published | skipped
    story_container_id: str | None = None
    story_media_id: str | None = None
    story_attempts: int = 0
    story_note: str | None = None      # last story error, why it waits or was skipped (pt-PT)
    caption: str | None = None         # the first attempt's caption: retries post and match it
    message_id: str | None = None      # Telegram (D38): the channel message (link in result_url)


@dataclass(frozen=True)
class Photo:
    destination: str
    file_path: str
    source: str
    source_url: str
    photographer: str
    photographer_url: str
    license: str
    fetched_at: datetime

"""View models: everything slides and captions show, formatted once, traceable to the DB."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from urllib.parse import urlsplit, urlunsplit

from escapadinha import i18n_pt as pt
from escapadinha.models import Deal, Observation, Photo

DISCLOSURE = ("Publicidade · Este post contém links de afiliado: se reservares através deles, "
              "podemos receber uma comissão, sem custo extra para ti.")
# The disclosure next to low prices' booking links on route pages (D24).
SITE_DISCLOSURE = ("Publicidade: os botões de reserva são links de afiliado. Se reservares através "
                   "deles, podemos receber uma comissão, sem custo extra para ti.")
# The disclosure in every affiliate block of an itinerary or tip (eSIM, insurance, activities, D37).
BLOCK_DISCLOSURE = ("Publicidade: esta ligação é um link de afiliado. Se comprares através dela, "
                    "podemos receber uma comissão, sem custo extra para ti.")
# Where a price was seen, as posts and pages name it (D47: an airline's own site is a source too).
SOURCE_LABELS = {"travelpayouts": "Aviasales", "ryanair": "Ryanair", "google_flights": "Google Flights"}
# Next to the booking button of a promotion whose link goes to the airline's own site (D47): no
# partner, no commission, so the site disclosure (which says the buttons are affiliate links)
# would be false there.
DIRECT_DISCLOSURE = ("Ligação direta ao site da companhia aérea: não recebemos comissão por "
                     "esta reserva.")


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def seller_label(o) -> str:
    """Where a price was seen, with the agency when the source is a metasearch: "Aviasales via
    Kiwi.com", "Aviasales", "Ryanair" (the comparison next to a promotion, D47)."""
    label = source_label(o.source)
    return f"{label} via {o.gate}" if o.gate and o.gate != label else label
# A post claims "−x % face ao habitual" only with this much confidence in the typical low (D44).
CLAIM_CONFIDENCE = ("medium", "high")


def booking_url(deep_link: str | None, booking_base: str) -> str | None:
    """Point an Aviasales link at the configured market site (e.g. aviasales.com -> .pt)."""
    if not deep_link:
        return None
    parts = urlsplit(deep_link)
    if not parts.netloc.removeprefix("www.").startswith("aviasales."):
        return deep_link
    base = urlsplit(booking_base)
    return urlunsplit(parts._replace(scheme=base.scheme, netloc=base.netloc))


@dataclass(frozen=True)
class PhotoCredit:
    file_uri: str | None
    photographer: str | None
    photographer_url: str | None
    source: str | None
    source_url: str | None

    @property
    def caption_line(self) -> str | None:
        if not self.photographer:
            return None
        return f"📷 Foto: {self.photographer} / {self.source}"

    @classmethod
    def from_photo(cls, photo: Photo | None, file_uri: str | None) -> PhotoCredit:
        if photo is None:
            return cls(None, None, None, None, None)
        return cls(file_uri, photo.photographer, photo.photographer_url,
                   photo.source.capitalize(), photo.source_url)


@dataclass(frozen=True)
class DealView:
    deal_id: int
    observation_id: int
    origin_iata: str
    destination_iata: str
    origin_city: str
    destination_city: str
    arrival_code: str | None      # 'BVA'
    arrival_airport: str | None   # 'Beauvais (BVA)'
    remote_airport: bool          # True: name the airport next to the city everywhere
    price: str            # '58 €'
    price_compact: str    # '58€'
    dates: str            # '6 a 9 de novembro'
    departure_month: str  # 'novembro'
    departure_short: str  # 'sex, 6 nov'
    return_short: str
    nights: str           # '3 noites'
    airline: str | None
    direct: bool | None
    discount_pct: int | None
    found_on: str | None  # '07/10/2026': day a traveller found the price (source cache)
    checked_at: str       # '12/10/2026 às 10:14': when we fetched it (Lisbon time)
    source_label: str
    affiliate_url: str | None     # tracked partner link (None if conversion failed)
    photo: PhotoCredit
    disclosure: str = DISCLOSURE
    # From the GraphQL match only (D43); None = unknown, and then no line is printed.
    baggage: bool | None = None           # a checked bag is included
    baggage_line: str | None = None       # 'com mala de porão incluída' / 'só bagagem de mão'
    gate: str | None = None               # the selling agency (reviewers see it; posts don't)
    # Stored at detection (D44); None for deals detected before.
    confidence: str | None = None         # low | medium | high: trust in the typical low
    new_low: bool | None = None           # cheaper than everything seen for the route-month

    @property
    def destination_headline(self) -> str:
        """'Paris (Beauvais)' for remote airports, else just the city."""
        if self.remote_airport:
            return f"{self.destination_city} ({pt.AIRPORTS.get(self.arrival_code, self.arrival_code)})"
        return self.destination_city

    @property
    def claimed_discount(self) -> int | None:
        """The "−x %" a post may claim (D44): only with medium or high confidence in the
        typical low. Captions and slides use this; the reviewer still sees `discount_pct`."""
        return self.discount_pct if self.confidence in CLAIM_CONFIDENCE else None

    @property
    def new_low_line(self) -> str | None:
        """'o preço mais baixo que vimos nesta rota para partidas em novembro' when the price
        beat everything seen for the route-month (D44), else None."""
        if not self.new_low:
            return None
        return f"o preço mais baixo que vimos nesta rota para partidas em {self.departure_month}"

    def meta(self, deal: Deal, observation: Observation, booking_base: str) -> dict:
        """Traceability record written next to the slides."""
        return {
            "deal_id": deal.id,
            "observation_id": observation.id,
            "run_id": observation.run_id,
            "source": observation.source,
            "fetched_at_utc": observation.fetched_at.isoformat(),
            "found_date": observation.found_date.isoformat() if observation.found_date else None,
            "price": observation.price,
            "currency": observation.currency,
            "route": observation.route_key,
            "departure_date": observation.departure_date.isoformat(),
            "return_date": observation.return_date.isoformat(),
            "airline": observation.airline,
            "with_baggage": observation.with_baggage,
            "baggage_code": observation.baggage_code,
            "gate": observation.gate,
            "found_at_utc": observation.found_at.isoformat() if observation.found_at else None,
            "rule": deal.rule,
            "baseline": "median of daily lowest prices, same route and departure month",
            "baseline_median": deal.baseline_median,
            "baseline_days": deal.sample_size,
            "discount_pct": deal.discount_pct,
            "threshold": deal.threshold,
            "affiliate_url": self.affiliate_url,
            "affiliate_error": deal.affiliate_error,
            "booking_url": booking_url(observation.deep_link, booking_base),
            "photo": asdict(self.photo),
        }


def _direct(o: Observation) -> bool | None:
    if o.transfers is None or o.return_transfers is None:
        return None
    return o.transfers == 0 and o.return_transfers == 0


def build_deal_view(deal: Deal, o: Observation, *, origin_city: str, destination_city: str,
                    photo: PhotoCredit) -> DealView:
    direct = _direct(o)
    return DealView(
        deal_id=deal.id, observation_id=o.id,
        origin_iata=o.origin, destination_iata=o.destination,
        origin_city=origin_city, destination_city=destination_city,
        arrival_code=o.destination_airport.upper() if o.destination_airport else None,
        arrival_airport=pt.airport_label(o.destination_airport),
        remote_airport=(o.destination_airport or "").upper() in pt.REMOTE_AIRPORTS,
        price=pt.eur(o.price), price_compact=pt.eur_compact(o.price),
        dates=pt.date_range(o.departure_date, o.return_date),
        departure_month=pt.MONTHS[o.departure_date.month - 1],
        departure_short=pt.short_date(o.departure_date), return_short=pt.short_date(o.return_date),
        nights=pt.nights(o.nights), airline=pt.airline_name(o.airline), direct=direct,
        discount_pct=None if deal.discount_pct is None else round(deal.discount_pct * 100),
        found_on=pt.numeric_date(o.found_date) if o.found_date else None,
        checked_at=pt.lisbon_timestamp(o.fetched_at),
        source_label=SOURCE_LABELS.get(o.source, o.source),
        affiliate_url=deal.affiliate_url,
        photo=photo,
        baggage=o.with_baggage, baggage_line=pt.baggage_line(o.with_baggage), gate=o.gate,
        confidence=deal.confidence, new_low=deal.new_low,
    )

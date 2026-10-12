"""View models: everything slides and captions show, formatted once, traceable to the DB."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from escapadinha import i18n_pt as pt
from escapadinha.models import Deal, Observation, Photo

DISCLOSURE = ("Publicidade · Este post contém links de afiliado: se reservares através deles, "
              "podemos receber uma comissão, sem custo extra para ti.")


def affiliate_link(deep_link: str | None, marker: str) -> str | None:
    """Append the Travelpayouts marker so bookings are attributed to us."""
    if not deep_link or not marker:
        return deep_link
    parts = urlsplit(deep_link)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "marker"] + [("marker", marker)]
    return urlunsplit(parts._replace(query=urlencode(query)))


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
    price: str            # '58 €'
    price_compact: str    # '58€'
    dates: str            # '6 a 9 de novembro'
    departure_short: str  # 'sex, 6 nov'
    return_short: str
    nights: str           # '3 noites'
    airline: str | None
    direct: bool | None
    discount_pct: int | None
    found_at: str         # '12/10/2026 às 10:14'
    source_label: str
    affiliate_url: str | None
    photo: PhotoCredit
    disclosure: str = DISCLOSURE

    def meta(self, deal: Deal, observation: Observation) -> dict:
        """Traceability record written next to the slides."""
        return {
            "deal_id": deal.id,
            "observation_id": observation.id,
            "run_id": observation.run_id,
            "source": observation.source,
            "fetched_at_utc": observation.fetched_at.isoformat(),
            "price": observation.price,
            "currency": observation.currency,
            "route": observation.route_key,
            "departure_date": observation.departure_date.isoformat(),
            "return_date": observation.return_date.isoformat(),
            "airline": observation.airline,
            "rule": deal.rule,
            "baseline_median": deal.baseline_median,
            "sample_size": deal.sample_size,
            "discount_pct": deal.discount_pct,
            "threshold": deal.threshold,
            "affiliate_url": self.affiliate_url,
            "photo": asdict(self.photo),
        }


def build_deal_view(deal: Deal, o: Observation, *, origin_city: str, destination_city: str,
                    marker: str, photo: PhotoCredit) -> DealView:
    if o.transfers is None or o.return_transfers is None:
        direct = None
    else:
        direct = o.transfers == 0 and o.return_transfers == 0
    return DealView(
        deal_id=deal.id, observation_id=o.id,
        origin_iata=o.origin, destination_iata=o.destination,
        origin_city=origin_city, destination_city=destination_city,
        price=pt.eur(o.price), price_compact=pt.eur_compact(o.price),
        dates=pt.date_range(o.departure_date, o.return_date),
        departure_short=pt.short_date(o.departure_date), return_short=pt.short_date(o.return_date),
        nights=pt.nights(o.nights), airline=pt.airline_name(o.airline), direct=direct,
        discount_pct=None if deal.discount_pct is None else round(deal.discount_pct * 100),
        found_at=pt.lisbon_timestamp(o.fetched_at),
        source_label="Aviasales" if o.source == "travelpayouts" else o.source,
        affiliate_url=affiliate_link(o.deep_link, marker),
        photo=photo,
    )

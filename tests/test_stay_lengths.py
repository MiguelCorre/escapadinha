"""The stay length per destination (D52): the repository's `routes.overrides` is the table of
`docs/research/2026-10-28-stay-length.md`, every entry sane, and the example that motivated it
(a 10-night Paris trip) is no longer a usable offer."""

import re
from datetime import date, timedelta
from pathlib import Path

from escapadinha import routes
from escapadinha.config import Context
from escapadinha.models import Observation

REPO = Path(__file__).resolve().parent.parent
NOTE = REPO / "docs" / "research" / "2026-10-28-stay-length.md"


def trip(nights: int, destination: str = "PAR") -> Observation:
    dep = date(2026, 12, 3)
    return Observation(source="test", origin="LIS", destination=destination, origin_airport="LIS",
                       destination_airport=destination, departure_date=dep,
                       return_date=dep + timedelta(days=nights), price=80, currency="EUR",
                       airline="TP", flight_number="1", transfers=0, return_transfers=0,
                       deep_link=None, fetched_at=None, raw_json="{}")


def test_every_override_is_a_destination_in_the_research_note_with_a_sane_range():
    cfg = Context(root=REPO).config.routes
    note = NOTE.read_text("utf-8")
    in_note = set(re.findall(r"^\| ([A-Z]{3}) \|", note, flags=re.M))
    assert cfg.overrides, "D52: the stay lengths live in config.yaml routes.overrides"
    for key, override in cfg.overrides.items():
        assert re.fullmatch(r"[A-Z]{3}", key), f"{key}: D52 keys overrides by destination"
        assert key in in_note, f"{key}: not in {NOTE.name}"
        assert override.min_nights is not None and override.max_nights is not None, key
        assert 1 <= override.min_nights <= override.max_nights, key
    assert in_note == set(cfg.overrides), "the note and config.yaml list the same destinations"


def test_a_ten_night_paris_trip_is_no_longer_a_usable_offer_but_a_long_weekend_is():
    cfg = Context(root=REPO).config.routes
    paris = routes.resolve_rules(cfg, "europe", "LIS", "PAR")
    assert (paris.min_nights, paris.max_nights) == (2, 5)           # Rough Guides: 3-5 days
    assert not paris.allows(trip(10)) and paris.allows(trip(3))
    assert routes.resolve_rules(cfg, "europe", "OPO", "PAR") == paris   # the same from Porto
    madeira = routes.resolve_rules(cfg, "domestic", "LIS", "FNC")
    assert (madeira.min_nights, madeira.max_nights) == (3, 10)       # Lonely Planet: at least 4 days
    new_york = routes.resolve_rules(cfg, "long_haul", "LIS", "NYC")
    assert (new_york.min_nights, new_york.max_nights) == (4, 8)      # a long weekend to 5 days
    assert new_york.max_transfers == 1 and not new_york.direct_only  # the kind's stops rule stays

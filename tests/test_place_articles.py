"""The article a destination's name takes in pt-PT (D66, config `destinations_article`),
exported in destinations.json for the site's "para a Madeira", "na Madeira", "do Porto"."""

import json
from pathlib import Path

import yaml

from escapadinha.config import AppConfig

REPO = Path(__file__).resolve().parents[1]
CONFIG = AppConfig.model_validate(yaml.safe_load((REPO / "config.yaml").read_text("utf-8")))
FIXTURES = REPO / "contract" / "site" / "v1" / "fixtures"


def test_a_city_that_is_an_origin_too_takes_the_same_article():
    for code, article in CONFIG.origins_article.items():
        if code in CONFIG.destinations_article:
            assert CONFIG.destinations_article[code] == article, code


def test_the_known_destinations_take_their_article():
    """The destinations with active routes on 2026-11-12 that take one; the rest take none."""
    article = CONFIG.destination_article
    assert [article(c) for c in ("FNC", "OPO", "TER", "MLE", "OVD", "DXB", "RIO", "LCG")] == \
        ["a", "o", "a", "as", "as", "o", "o", "a"]
    assert [article(c) for c in ("PAR", "LON", "MLA", "IBZ", "TCI", "SAO")] == [None] * 6


def test_every_fixture_destination_carries_the_configured_article():
    """The committed fixture (an export of run 1711, D40) got `article` by hand (D66), with the
    value a regeneration writes: config's, null for none."""
    for d in json.loads((FIXTURES / "destinations.json").read_text("utf-8"))["destinations"]:
        assert "article" in d and d["article"] == CONFIG.destination_article(d["code"]), d["code"]


def test_an_island_named_ilha_takes_a():
    names = {"CVU": "Ilha do Corvo", "FLW": "Ilha das Flores", "GRW": "Ilha Graciosa",
             "PIX": "Ilha do Pico", "SID": "Ilha do Sal", "SJZ": "Ilha de São Jorge"}
    assert {c: CONFIG.destination_article(c) for c in names} == dict.fromkeys(names, "a")

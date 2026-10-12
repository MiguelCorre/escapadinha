from datetime import date, datetime, timezone

import pytest

from escapadinha import i18n_pt as pt
from escapadinha.captions import deal_caption, guide_caption
from escapadinha.guides import Guide
from escapadinha.models import Deal, Observation, Photo
from escapadinha.presentation import DISCLOSURE, PhotoCredit, affiliate_link, build_deal_view

FETCHED = datetime(2026, 10, 12, 9, 14, tzinfo=timezone.utc)


def observation(**overrides):
    fields = dict(
        id=7, run_id=3, source="travelpayouts", origin="LIS", destination="AMS",
        origin_airport="LIS", destination_airport="AMS", departure_date=date(2026, 11, 27),
        return_date=date(2026, 12, 4), price=58.0, currency="EUR", airline="HV",
        flight_number="6640", transfers=0, return_transfers=0,
        deep_link="https://www.aviasales.com/search/LIS2711AMS04121?t=x",
        fetched_at=FETCHED, raw_json="{}",
    )
    return Observation(**(fields | overrides))


def deal(rule="median", discount=0.4123):
    return Deal(id=11, observation_id=7, rule=rule, baseline_median=99.0, sample_size=30,
                discount_pct=discount if rule == "median" else None, threshold=0.3,
                detected_at=FETCHED, status="new")


PHOTO = Photo(destination="AMS", file_path="assets/photos/AMS.jpg", source="pixabay",
              source_url="https://pixabay.com/photos/x-1/", photographer="Ana Silva",
              photographer_url="https://pixabay.com/users/ana-1/", license="Pixabay Content License",
              fetched_at=FETCHED)


def view(o=None, d=None, photo=PHOTO):
    return build_deal_view(d or deal(), o or observation(), origin_city="Lisboa",
                           destination_city="Amesterdão", marker="12345",
                           photo=PhotoCredit.from_photo(photo, None))


def caption(**kw):
    return deal_caption(view(**kw), brand_name="Escapadinha")


# --- pt-PT formatting -----------------------------------------------------------

@pytest.mark.parametrize("amount, expected", [(58, "58 €"), (58.0, "58 €"), (49.5, "49,50 €"),
                                              (1299, "1299 €")])
def test_eur(amount, expected):
    assert pt.eur(amount) == expected


def test_eur_compact():
    assert pt.eur_compact(49) == "49€"


@pytest.mark.parametrize("start, end, expected", [
    (date(2026, 11, 6), date(2026, 11, 9), "6 a 9 de novembro"),
    (date(2026, 11, 27), date(2026, 12, 4), "27 de novembro a 4 de dezembro"),
    (date(2026, 12, 28), date(2027, 1, 3), "28 de dezembro de 2026 a 3 de janeiro de 2027"),
    (date(2026, 3, 1), date(2026, 3, 5), "1 a 5 de março"),
])
def test_date_range(start, end, expected):
    assert pt.date_range(start, end) == expected


def test_short_date_and_nights():
    assert pt.short_date(date(2026, 11, 6)) == "sex, 6 nov"
    assert pt.nights(1) == "1 noite" and pt.nights(3) == "3 noites"


def test_lisbon_timestamp_handles_summer_and_winter_time():
    assert pt.lisbon_timestamp(FETCHED) == "12/10/2026 às 10:14"            # WEST, UTC+1
    assert pt.lisbon_timestamp(datetime(2026, 12, 1, 9, 14, tzinfo=timezone.utc)) == \
        "01/12/2026 às 09:14"                                                  # WET, UTC+0


def test_hashtag_strips_accents():
    assert pt.hashtag("Amesterdão") == "#amesterdao"
    assert pt.hashtag("Milão") == "#milao"


# --- deal caption ---------------------------------------------------------------

def test_deal_caption_contains_price_dates_and_traceable_timestamp():
    text = caption()
    assert "Lisboa → Amesterdão desde 58 € ida e volta" in text
    assert "27 de novembro a 4 de dezembro · 7 noites" in text
    assert ("7 noites\n🛫 Transavia · voos diretos\n🛬 Chegada: aeroporto Schiphol (AMS)\n"
            "📉 41% abaixo do preço mínimo habitual "
            "desta rota para partidas em novembro") in text
    assert "verificado a 12/10/2026 às 10:14 (hora de Lisboa) via Aviasales" in text


def test_caption_states_when_price_was_found_and_when_checked():
    text = caption(o=observation(found_date=date(2026, 10, 9)))
    assert ("Preço por pessoa encontrado a 09/10/2026 via Aviasales e verificado a "
            "12/10/2026 às 10:14 (hora de Lisboa).") in text


def test_deal_caption_always_has_disclosure():
    assert DISCLOSURE in caption()
    assert DISCLOSURE in caption(d=deal(rule="price_cap"))
    assert DISCLOSURE in caption(photo=None)
    assert DISCLOSURE.startswith("Publicidade")


def test_price_cap_deal_makes_no_discount_claim():
    assert "abaixo" not in caption(d=deal(rule="price_cap"))


def test_photo_credit_line():
    assert "📷 Foto: Ana Silva / Pixabay" in caption()
    assert "📷" not in caption(photo=None)


def test_unknown_transfers_omits_direct_claim():
    text = caption(o=observation(transfers=None))
    assert "diretos" not in text and "escala" not in text


def test_caption_has_no_runs_of_blank_lines_and_has_hashtags():
    text = caption()
    assert "\n\n\n" not in text
    assert text.rstrip().splitlines()[-1].startswith("#amesterdao #lisboa")


def test_affiliate_link_adds_or_replaces_marker():
    assert affiliate_link("https://a.com/s?t=x", "99") == "https://a.com/s?t=x&marker=99"
    assert affiliate_link("https://a.com/s?marker=1", "99") == "https://a.com/s?marker=99"
    assert affiliate_link("https://a.com/s", "") == "https://a.com/s"
    assert affiliate_link(None, "99") is None


# --- guide caption --------------------------------------------------------------

def guide(**overrides):
    fields = dict(slug="x", title="T", tips=[{"title": f"Dica {i}", "body": "b"} for i in range(3)],
                  cta="Guarda este post", caption="Intro do guia.", hashtags=["#viagens"])
    return Guide.model_validate(fields | overrides)


def test_guide_caption_lists_tips_and_disclosure_only_when_affiliate():
    credit = PhotoCredit.from_photo(None, None)
    plain = guide_caption(guide(), credit)
    assert "1. Dica 0\n2. Dica 1\n3. Dica 2" in plain
    assert DISCLOSURE not in plain
    assert DISCLOSURE in guide_caption(guide(affiliate=True), credit)


# --- arrival airport --------------------------------------------------------------

def test_arrival_airport_is_always_named():
    assert "🛬 Chegada: aeroporto Schiphol (AMS)" in caption()


def test_remote_airport_is_named_in_the_headline():
    v = build_deal_view(deal(), observation(destination="PAR", destination_airport="BVA"),
                        origin_city="Porto", destination_city="Paris", marker="1",
                        photo=PhotoCredit.from_photo(None, None))
    text = deal_caption(v, brand_name="Escapadinha")
    assert text.startswith("✈️ Porto → Paris (Beauvais) desde 58 €")
    assert "🛬 Chegada: aeroporto Beauvais (BVA)" in text


def test_unknown_airport_code_shown_bare():
    assert pt.airport_label("XYZ") == "XYZ" and pt.airport_label(None) is None

from datetime import date, datetime, timezone

import pytest

from escapadinha import i18n_pt as pt
from escapadinha.captions import deal_caption, guide_caption, whatsapp_text
from escapadinha.guides import Guide
from escapadinha.models import Deal, Observation, Photo
from escapadinha.presentation import DISCLOSURE, PhotoCredit, build_deal_view

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


def deal(rule="median", discount=0.4123, confidence="medium", new_low=None):
    return Deal(id=11, observation_id=7, rule=rule, baseline_median=99.0, sample_size=30,
                discount_pct=discount if rule == "median" else None, threshold=0.3,
                detected_at=FETCHED, status="new", confidence=confidence, new_low=new_low)


PHOTO = Photo(destination="AMS", file_path="assets/photos/AMS.jpg", source="pixabay",
              source_url="https://pixabay.com/photos/x-1/", photographer="Ana Silva",
              photographer_url="https://pixabay.com/users/ana-1/", license="Pixabay Content License",
              fetched_at=FETCHED)


def view(o=None, d=None, photo=PHOTO):
    return build_deal_view(d or deal(), o or observation(), origin_city="Lisboa",
                           destination_city="Amesterdão",
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


def test_numbers_and_counted_nouns():
    assert pt.number(24) == "24" and pt.number(24.0) == "24" and pt.number(1.5) == "1,5"
    assert pt.number(0.25) == "0,25"
    assert pt.count(1, "decisão pendente", "decisões pendentes") == "1 decisão pendente"
    assert pt.count(2, "decisão pendente", "decisões pendentes") == "2 decisões pendentes"
    assert pt.count(0, "decisão pendente", "decisões pendentes") == "0 decisões pendentes"


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


CLAIM = "📉 41% abaixo do preço mínimo habitual desta rota para partidas em novembro"
NEW_LOW = "o preço mais baixo que vimos nesta rota para partidas em novembro"


def test_the_percentage_is_claimed_only_with_medium_or_high_confidence():
    """D44: the caption says "−x %" only when the typical low is trusted; a deal detected
    before D44 (no stored confidence) makes no claim either."""
    assert CLAIM in caption(d=deal(confidence="medium"))
    assert CLAIM in caption(d=deal(confidence="high"))
    for d in (deal(confidence="low"), deal(confidence=None)):
        text = caption(d=d)
        assert "📉" not in text and "abaixo" not in text and "habitual" not in text


def test_a_new_low_is_said_as_such_and_alone_when_the_typical_low_is_not_trusted():
    assert f"{CLAIM}: o preço mais baixo que vimos\n" in caption(d=deal(new_low=True))
    low = caption(d=deal(confidence="low", new_low=True))
    assert f"📉 {NEW_LOW[0].upper()}{NEW_LOW[1:]}\n" in low and "abaixo" not in low
    assert "mais baixo" not in caption(d=deal(new_low=False))
    cap = caption(d=deal(rule="price_cap", confidence="low", new_low=True))
    assert "mais baixo que vimos" in cap and "abaixo" not in cap


def test_photo_credit_line():
    assert "📷 Foto: Ana Silva / Pixabay" in caption()
    assert "📷" not in caption(photo=None)


def test_baggage_line_only_when_the_graphql_match_said_so():
    text = caption()
    assert "🧳" not in text and "bagagem" not in text and "mala" not in text   # unknown: no guess
    text = caption(o=observation(with_baggage=False, baggage_code="0PC", gate="Kiwi.com"))
    assert "🛬 Chegada: aeroporto Schiphol (AMS)\n🧳 Só bagagem de mão\n📉" in text
    assert "Kiwi.com" not in text                     # the agency is for reviewers, not posts
    assert "🧳 Com mala de porão incluída" in caption(o=observation(with_baggage=True))


def test_baggage_words():
    assert pt.baggage_line(True) == "com mala de porão incluída"
    assert pt.baggage_line(False) == "só bagagem de mão"
    assert pt.baggage_line(None) is None


def test_unknown_transfers_omits_direct_claim():
    text = caption(o=observation(transfers=None))
    assert "diretos" not in text and "escala" not in text


def test_caption_has_no_runs_of_blank_lines_and_has_hashtags():
    text = caption()
    assert "\n\n\n" not in text
    assert text.rstrip().splitlines()[-1].startswith("#amesterdao #lisboa")


# --- WhatsApp text (D32) -----------------------------------------------------------

LINK = "https://aviasales.tpo.lu/deal-11"


def linked_deal(**kw):
    from dataclasses import replace
    return replace(deal(**kw), affiliate_url=LINK)


def test_whatsapp_text_is_short_pt_pt_with_link_disclosure_and_both_dates():
    text = whatsapp_text(view(o=observation(found_date=date(2026, 10, 9)), d=linked_deal()))
    assert text == (
        "✈️ Lisboa → Amesterdão desde 58 € ida e volta\n"
        "📅 27 de novembro a 4 de dezembro · 7 noites\n"
        "🛫 Transavia · voos diretos\n"
        "🛬 Chegada: aeroporto Schiphol (AMS)\n"
        f"{CLAIM}\n"
        "\n"
        "Preço por pessoa encontrado a 09/10/2026 e verificado a 12/10/2026 às 10:14 "
        "(hora de Lisboa). Os preços mudam depressa.\n"
        "\n"
        f"👉 {LINK}\n"
        "\n"
        f"{DISCLOSURE}\n")


def test_whatsapp_text_carries_the_baggage_line_when_known():
    text = whatsapp_text(view(o=observation(with_baggage=True), d=linked_deal()))
    assert f"🛬 Chegada: aeroporto Schiphol (AMS)\n🧳 Com mala de porão incluída\n{CLAIM}\n\n" in text
    assert "🧳" not in whatsapp_text(view(d=linked_deal()))


def test_whatsapp_text_claims_the_percentage_only_with_a_trusted_typical_low():
    """D44: the same claim line as the caption, or "o preço mais baixo que vimos" alone."""
    assert CLAIM in whatsapp_text(view(d=linked_deal(confidence="high")))
    low = whatsapp_text(view(d=linked_deal(confidence="low", new_low=True)))
    assert "📉 O preço mais baixo que vimos nesta rota para partidas em novembro\n" in low
    assert "abaixo" not in low
    assert "📉" not in whatsapp_text(view(d=linked_deal(confidence="low")))


def test_whatsapp_text_without_a_found_date_says_only_when_it_was_checked():
    text = whatsapp_text(view(d=linked_deal()))
    assert "Preço por pessoa verificado a 12/10/2026 às 10:14 (hora de Lisboa)." in text
    assert "encontrado" not in text and "#" not in text


def test_whatsapp_text_names_a_remote_airport_in_the_headline():
    v = build_deal_view(linked_deal(), observation(destination="PAR", destination_airport="BVA"),
                        origin_city="Porto", destination_city="Paris",
                        photo=PhotoCredit.from_photo(None, None))
    text = whatsapp_text(v)
    assert text.startswith("✈️ Porto → Paris (Beauvais) desde 58 €")
    assert "🛬 Chegada: aeroporto Beauvais (BVA)" in text


def test_whatsapp_text_needs_the_stored_partner_link():
    with pytest.raises(ValueError):
        whatsapp_text(view())


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
                        origin_city="Porto", destination_city="Paris",
                        photo=PhotoCredit.from_photo(None, None))
    text = deal_caption(v, brand_name="Escapadinha")
    assert text.startswith("✈️ Porto → Paris (Beauvais) desde 58 €")
    assert "🛬 Chegada: aeroporto Beauvais (BVA)" in text


def test_unknown_airport_code_shown_bare():
    assert pt.airport_label("XYZ") == "XYZ" and pt.airport_label(None) is None


def test_booking_url_moves_aviasales_links_to_configured_market():
    from escapadinha.presentation import booking_url
    assert booking_url("https://www.aviasales.com/search/X?t=1", "https://www.aviasales.pt") ==         "https://www.aviasales.pt/search/X?t=1"
    assert booking_url("https://example.com/a", "https://www.aviasales.pt") == "https://example.com/a"
    assert booking_url(None, "https://www.aviasales.pt") is None

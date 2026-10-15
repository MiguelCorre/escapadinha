"""The approval live check, pipeline side, on the cases the review Function's port must agree
with (contract/review/v1/fixtures/live-check-cases.json; web/test/review/live-check.test.ts
runs the same file through web/functions/_lib/review/live-check.ts, D29)."""

import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from escapadinha import pipeline
from escapadinha.collector.travelpayouts import (API_URL, TravelpayoutsSource, parse_response,
                                                 request_params)
from escapadinha.config import DetectorConfig
from escapadinha.models import Observation, RouteRules
from escapadinha.recheck import recheck

CASES = json.loads((Path(__file__).parent.parent / "contract" / "review" / "v1" / "fixtures"
                    / "live-check-cases.json").read_text("utf-8"))
TRANSFERS = {True: (0, 0), False: (1, 1), None: (None, None)}


def run(case: dict):
    defaults = CASES["defaults"]
    deal = {**defaults["deal"], **case.get("deal", {})}
    now = datetime.fromisoformat(case.get("now", defaults["now"]))
    payload = case.get("payload") or {
        "success": True, "currency": "eur",
        "data": [{**defaults["item"], **item} for item in case["items"]]}
    r = deal["rules"]
    rules = RouteRules(direct_only=r["direct_only"], max_transfers=r["max_transfers"],
                       min_nights=r["min_nights"], max_nights=r["max_nights"])
    # The snapshot's stop counts when the case has them, else what `direct` stands for.
    transfers, return_transfers = ((deal["transfers"], deal["return_transfers"])
                                   if "transfers" in deal else TRANSFERS[deal["direct"]])
    deal_obs = Observation(
        source="travelpayouts", origin=deal["origin"], destination=deal["destination"],
        origin_airport=None, destination_airport=None,
        departure_date=date.fromisoformat(deal["departure_date"]),
        return_date=date.fromisoformat(deal["return_date"]), price=float(deal["price_eur"]),
        currency="EUR", airline=None, flight_number=None, transfers=transfers,
        return_transfers=return_transfers, deep_link=None, fetched_at=now)
    # What pipeline.price_now does: parse the route-month with the route's nights range...
    latest = parse_response(payload, origin=deal["origin"], destination=deal["destination"],
                            fetched_at=now, min_nights=r["min_nights"], max_nights=r["max_nights"])
    # ...and apply the recheck rule.
    return recheck(deal_obs, latest, DetectorConfig(max_offer_age_days=r["max_offer_age_days"]),
                   now, rules=rules)


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_pipeline_live_check_matches_the_shared_cases(case):
    expected = case["expected"]
    result = run(case)
    assert (result.valid, result.latest_price, result.reason) == (
        expected["valid"], expected["price_eur"], expected["reason"])


FAILURES = CASES["failures"]["cases"]


@pytest.mark.parametrize("case", FAILURES, ids=[c["name"] for c in FAILURES])
@respx.mock
def test_provider_failures_read_as_the_shared_pt_reasons(case):
    """What pipeline.price_now / live_check raise: the source's request, then check_failure."""
    if case.get("network_error"):
        respx.get(API_URL).mock(side_effect=httpx.ConnectError("network down"))
    elif "http_status" in case:
        respx.get(API_URL).mock(return_value=httpx.Response(case["http_status"], text=case["body"]))
    elif "payload" in case:
        respx.get(API_URL).mock(return_value=httpx.Response(200, json=case["payload"]))
    with pytest.raises(Exception) as exc:
        source = TravelpayoutsSource(case.get("token", "tp-token"), currency="eur", limit=1000,
                                     sleep=lambda _: None)
        source.fetch("LIS", "LON", date(2026, 11, 1), rules=RouteRules())
    assert pipeline.check_failure(exc.value) == case["expected"]


QUERIES = CASES["queries"]


@pytest.mark.parametrize("case", QUERIES["cases"], ids=[c["name"] for c in QUERIES["cases"]])
def test_the_live_check_query_matches_the_shared_cases(case):
    """What the collection, pipeline.price_now and the snapshot's live_check.query ask (D39)."""
    r = case["rules"]
    rules = RouteRules(direct_only=r["direct_only"], max_transfers=r["max_transfers"],
                       min_nights=r["min_nights"], max_nights=r["max_nights"])
    c = QUERIES["collector"]
    query = request_params(case["origin"], case["destination"],
                           date.fromisoformat(f"{case['month']}-01"), rules,
                           currency=c["currency"], limit=c["limit"], market=c["market"])
    assert query == case["expected"]

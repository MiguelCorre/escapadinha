"""The approval live check, pipeline side, on the cases the review Function's port must agree
with (contract/review/v1/fixtures/live-check-cases.json; web/test/review/live-check.test.ts
runs the same file through web/functions/_lib/review/live-check.ts, D29)."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from escapadinha.collector.travelpayouts import TravelpayoutsError, parse_response
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
    transfers, return_transfers = TRANSFERS[deal["direct"]]
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
    if "error" in expected:
        with pytest.raises(TravelpayoutsError, match=f"^{expected['error']}$"):
            run(case)
        return
    result = run(case)
    assert (result.valid, result.latest_price, result.reason) == (
        expected["valid"], expected["price_eur"], expected["reason"])

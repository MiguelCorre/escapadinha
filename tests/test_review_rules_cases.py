"""The review rules and event text, pipeline side, against
contract/review/v1/fixtures/review-rules.json: the review Function's port
(web/functions/_lib/review/rules.ts, events.ts) is checked against the same file by
web/test/review/rules.test.ts, so the two can't drift apart (D29)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from escapadinha import review
from escapadinha.review import ReviewError, check_decision
from escapadinha.review_events import Event
from escapadinha.storage import db

RULES = json.loads((Path(__file__).parent.parent / "contract" / "review" / "v1" / "fixtures"
                    / "review-rules.json").read_text("utf-8"))


def test_tables_match_the_shared_fixture():
    assert {k: sorted(v) for k, v in review.TRANSITIONS.items()} == RULES["transitions"]
    assert review.STATUS_PT == RULES["status_pt"]
    assert review.DECISIONS == RULES["decisions"]
    assert review.DECISION_PT == RULES["decision_pt"]
    assert review.CONFIDENCE_PT == RULES["confidence_pt"]
    assert list(db.OPEN_STATUSES) == RULES["open_statuses"]


@pytest.mark.parametrize("case", RULES["check_decision"],
                         ids=[f"{c['kind']}-{c['status']}-{i}" for i, c in enumerate(RULES["check_decision"])])
def test_check_decision_matches_the_shared_cases(case):
    kwargs = {"affiliate_url": case["affiliate_url"], "post_url": case.get("post_url")}
    expected = case["expected"]
    if "error" in expected:
        with pytest.raises(ReviewError) as exc:
            check_decision(case["kind"], case["status"], **kwargs)
        assert str(exc.value) == expected["error"]
    else:
        assert check_decision(case["kind"], case["status"], **kwargs) == expected["status"]


@pytest.mark.parametrize("case", RULES["new_event_text"]["cases"], ids=repr)
def test_event_text_matches_the_shared_cases(case):
    event = Event.new("published", 1, actor="test", now=datetime(2026, 10, 14, tzinfo=UTC),
                      note=case["given"], post_url=case["given"])
    assert (event.note, event.post_url) == (case["expected"], case["expected"])

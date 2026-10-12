import json

import httpx
import pytest
import respx

from escapadinha.affiliate import API_URL, AffiliateError, PartnerLinksClient


def ok_response(request):
    body = json.loads(request.content)
    links = [{"url": l["url"], "code": "success", "partner_url": f"https://aviasales.tpo.lu/{i}"}
             for i, l in enumerate(body["links"])]
    return httpx.Response(200, json={"result": {**body, "links": links}, "code": "success",
                                     "status": 200})


def client(**kw):
    return PartnerLinksClient("tok", marker="789000", project_id=584711, **kw)


@respx.mock
def test_sends_project_marker_and_sub_ids():
    route = respx.post(API_URL).mock(side_effect=ok_response)
    result = client().create([("https://www.aviasales.com/search/A", "deal-1")])
    sent = json.loads(route.calls.last.request.content)
    assert route.calls.last.request.headers["X-Access-Token"] == "tok"
    assert sent == {"trs": 584711, "marker": 789000, "shorten": True,
                    "links": [{"url": "https://www.aviasales.com/search/A", "sub_id": "deal-1"}]}
    assert result["https://www.aviasales.com/search/A"].partner_url == "https://aviasales.tpo.lu/0"


@respx.mock
def test_batches_at_most_ten_links_per_request():
    route = respx.post(API_URL).mock(side_effect=ok_response)
    links = [(f"https://www.aviasales.com/search/{i}", None) for i in range(23)]
    result = client().create(links)
    assert [len(json.loads(c.request.content)["links"]) for c in route.calls] == [10, 10, 3]
    assert len(result) == 23 and all(r.partner_url for r in result.values())


@respx.mock
def test_failed_link_is_reported_not_faked():
    respx.post(API_URL).mock(return_value=httpx.Response(200, json={
        "result": {"links": [{"url": "u", "code": "failed", "partner_url": "",
                              "message": "trs is not subscribed for brand"}]},
        "code": "success", "status": 200}))
    link = client().create([("u", None)])["u"]
    assert link.partner_url is None and link.error == "trs is not subscribed for brand"


@respx.mock
def test_request_errors_raise():
    respx.post(API_URL).mock(return_value=httpx.Response(
        400, json={"code": "incorrect_request_body", "error": "invalid traffic source", "status": 400}))
    with pytest.raises(AffiliateError, match="invalid traffic source"):
        client().create([("u", None)])


@respx.mock
def test_invalid_token():
    respx.post(API_URL).mock(return_value=httpx.Response(401))
    with pytest.raises(AffiliateError, match="401"):
        client().create([("u", None)])


def test_config_validation():
    with pytest.raises(AffiliateError, match="TOKEN"):
        PartnerLinksClient("", marker="1", project_id=1)
    with pytest.raises(AffiliateError, match="MARKER"):
        PartnerLinksClient("t", marker="", project_id=1)

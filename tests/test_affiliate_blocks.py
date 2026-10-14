"""Affiliate blocks in itineraries and tips (#18, D37): the programmes come from config.yaml,
the articles that use them from the MDX front matter (`affiliates:`), and each link is created
once per (programme, article) through the partner links API (sub_id per article), stored in the
database and exported in the website contract (`affiliates.json`)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from pydantic import ValidationError

from escapadinha import articles, pipeline, site_data
from escapadinha.affiliate import API_URL as LINKS_URL
from escapadinha.config import AffiliateConfig, AppConfig, Context
from escapadinha.storage import db
from test_pipeline import REPO, ctx  # noqa: F401

ITINERARY = """---
title: Roma em 3 dias
description: Um roteiro.
destination: ROM
days: 3
affiliates: [esim, insurance, activities]
reviewed: true
last_checked: 2026-10-14
sources:
  - title: Fonte
    url: https://example.com/fonte
---

<EsimBlock />
"""


PROGRAMMES = {
    "esim": {"brand": "Yesim", "url": "https://yesim.tech"},
    "activities": {"brand": "Tiqets", "url": "https://tiqets.com"},
    "insurance": None,
}


def configure(ctx, programmes: dict) -> None:
    """Set `affiliate.programmes` in the test project's config.yaml."""
    path = ctx.root / "config.yaml"
    config = yaml.safe_load(path.read_text("utf-8"))
    config["affiliate"]["programmes"] = programmes
    path.write_text(yaml.safe_dump(config, allow_unicode=True), "utf-8")
    ctx.__dict__.pop("config", None)


def write_article(ctx, kind: str, slug: str, text: str, folder: str = "src/content") -> Path:
    path = ctx.root / "web" / folder / kind / f"{slug}.mdx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


def mock_partner_links():
    """The partner links API, answering each (url, sub_id) with a distinct tracked link."""
    def respond(request):
        body = json.loads(request.content)
        links = [{"url": link["url"], "code": "success",
                  "partner_url": f"https://tp.example/{link['sub_id']}/{link['url'].split('/')[2]}"}
                 for link in body["links"]]
        return httpx.Response(200, json={"result": {**body, "links": links}, "code": "success"})
    return respx.post(LINKS_URL).mock(side_effect=respond)


def sent(route) -> list[tuple[str, str]]:
    return [(link["url"], link["sub_id"]) for call in route.calls
            for link in json.loads(call.request.content)["links"]]


def affiliates(out: Path) -> dict:
    return json.loads((out / "affiliates.json").read_text("utf-8"))


@respx.mock
def test_export_creates_one_link_per_configured_programme_and_article(ctx, tmp_path):  # noqa: F811
    configure(ctx, PROGRAMMES)
    write_article(ctx, "itineraries", "roma-em-3-dias", ITINERARY)
    api = mock_partner_links()
    conn = pipeline.open_db(ctx)
    out = tmp_path / "data"

    site_data.export_site_data(ctx, conn, out)

    assert sorted(sent(api)) == [("https://tiqets.com", "roteiro-roma-em-3-dias"),
                                 ("https://yesim.tech", "roteiro-roma-em-3-dias")]
    doc = affiliates(out)
    assert doc["programmes"] == {"esim": {"brand": "Yesim"}, "activities": {"brand": "Tiqets"},
                                 "insurance": None}
    assert doc["links"] == [
        {"article": "itineraries/roma-em-3-dias", "programme": "activities",
         "url": "https://tp.example/roteiro-roma-em-3-dias/tiqets.com"},
        {"article": "itineraries/roma-em-3-dias", "programme": "esim",
         "url": "https://tp.example/roteiro-roma-em-3-dias/yesim.tech"},
    ]
    assert json.loads((out / "meta.json").read_text("utf-8"))["files"]["affiliates"] == "affiliates.json"


@respx.mock
def test_each_link_is_created_once_and_kept_in_the_database(ctx, tmp_path):  # noqa: F811
    configure(ctx, PROGRAMMES)
    write_article(ctx, "itineraries", "roma-em-3-dias", ITINERARY)
    api = mock_partner_links()
    conn = pipeline.open_db(ctx)

    site_data.export_site_data(ctx, conn, tmp_path / "a", new_links=False)
    assert api.call_count == 0 and affiliates(tmp_path / "a")["links"] == []
    site_data.export_site_data(ctx, conn, tmp_path / "b")
    assert api.call_count == 1                                  # one request per article
    site_data.export_site_data(ctx, conn, tmp_path / "c")
    site_data.export_site_data(ctx, conn, tmp_path / "d", new_links=False)
    assert api.call_count == 1
    assert affiliates(tmp_path / "c") == affiliates(tmp_path / "d") == affiliates(tmp_path / "b")


@respx.mock
def test_links_of_unpublished_articles_and_other_projects_are_forgotten(ctx, tmp_path):  # noqa: F811
    """An article taken off the site (back to draft, deleted) and a Project switch drop the stored
    links: an article that comes back, or a Project switched back, gets fresh ones."""
    configure(ctx, PROGRAMMES)
    path = write_article(ctx, "itineraries", "roma-em-3-dias", ITINERARY)
    api = mock_partner_links()
    conn = pipeline.open_db(ctx)
    export = lambda: site_data.export_site_data(ctx, conn, tmp_path / "data")  # noqa: E731

    export()
    path.write_text(ITINERARY.replace("reviewed: true", "reviewed: false"), "utf-8")
    export()
    path.write_text(ITINERARY, "utf-8")
    export()
    assert api.call_count == 2                     # created again after coming back

    ctx.config.affiliate.projects["website"] = 999999
    export()
    ctx.config.affiliate.projects["website"] = None    # back to the Instagram Project's
    export()
    assert api.call_count == 4
    assert len(affiliates(tmp_path / "data")["links"]) == 2


TIP = """---
title: Internet em viagem
description: Uma dica.
topic: esim
affiliates: [esim]
reviewed: true
---
"""


def fixture_copy(text: str) -> str:
    return text.replace("reviewed: true", "reviewed: true\nfixture: true")


@respx.mock
def test_only_published_articles_and_the_programmes_they_list_get_links(ctx, tmp_path):  # noqa: F811
    configure(ctx, PROGRAMMES)
    write_article(ctx, "itineraries", "roma-em-3-dias",
                  ITINERARY.replace("reviewed: true", "reviewed: false"))       # a draft
    write_article(ctx, "tips", "internet-em-viagem", TIP)
    write_article(ctx, "itineraries", "teste", fixture_copy(ITINERARY), folder="test/fixtures/content")
    api = mock_partner_links()
    conn = pipeline.open_db(ctx)

    site_data.export_site_data(ctx, conn, tmp_path / "data")

    assert sent(api) == [("https://yesim.tech", "dica-internet-em-viagem")]
    assert affiliates(tmp_path / "data")["links"] == [
        {"article": "tips/internet-em-viagem", "programme": "esim",
         "url": "https://tp.example/dica-internet-em-viagem/yesim.tech"}]


@respx.mock
def test_an_itinerary_links_its_citys_page_when_config_has_one(ctx, tmp_path):  # noqa: F811
    rome = "https://tiqets.com/pt/roma"
    configure(ctx, {**PROGRAMMES, "activities": {"brand": "Tiqets", "url": "https://tiqets.com",
                                                 "destinations": {"ROM": rome}}})
    write_article(ctx, "itineraries", "roma-em-3-dias", ITINERARY)
    api = mock_partner_links()
    conn = pipeline.open_db(ctx)
    site_data.export_site_data(ctx, conn, tmp_path / "data")
    assert (rome, "roteiro-roma-em-3-dias") in sent(api)

    # The page changes in config: the next export makes a new link for the new page.
    configure(ctx, PROGRAMMES)
    site_data.export_site_data(ctx, conn, tmp_path / "data")
    assert sent(api)[-1] == ("https://tiqets.com", "roteiro-roma-em-3-dias")
    [activities] = [lk for lk in affiliates(tmp_path / "data")["links"]
                    if lk["programme"] == "activities"]
    assert activities["url"] == "https://tp.example/roteiro-roma-em-3-dias/tiqets.com"


@respx.mock
def test_a_failed_link_is_left_out_and_retried_on_the_next_export(ctx, tmp_path):  # noqa: F811
    configure(ctx, PROGRAMMES)
    write_article(ctx, "itineraries", "roma-em-3-dias", ITINERARY)
    respx.post(LINKS_URL).mock(return_value=httpx.Response(500, json={"code": "error"}))
    conn = pipeline.open_db(ctx)
    site_data.export_site_data(ctx, conn, tmp_path / "data")
    assert affiliates(tmp_path / "data")["links"] == []

    respx.reset()
    api = mock_partner_links()
    site_data.export_site_data(ctx, conn, tmp_path / "data")
    assert api.call_count == 1 and len(affiliates(tmp_path / "data")["links"]) == 2


GATE_CASES = json.loads((REPO / "web" / "test" / "fixtures" / "content-gate-cases.json")
                        .read_text("utf-8"))["cases"]


@pytest.mark.parametrize("case", GATE_CASES, ids=[c["name"] for c in GATE_CASES])
def test_articles_read_the_front_matter_as_the_site_does(case, tmp_path):
    """The shared cases (also checked by web/test/content.test.ts on the zod schemas and Astro's
    YAML parser): the articles that get affiliate links are exactly the ones the site builds."""
    web = tmp_path / "web"
    path = web / articles.CONTENT / case["kind"] / f"{case['slug']}.mdx"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\n{case['front_matter']}\n---\n\nTexto.\n", "utf-8")
    if case["error"]:
        with pytest.raises(articles.ArticleError, match=case["slug"]):
            articles.load(web / articles.CONTENT)
        return
    [article] = articles.load(web / articles.CONTENT)
    assert (article.key, list(article.affiliates)) == (case["key"], case["affiliates"])
    published = {"site": articles.published(web, fixture=False),
                 "fixture_site": articles.published(web, fixture=True)}
    assert {k: v == [article] for k, v in published.items()} == case["published"]


@pytest.mark.parametrize("programmes, problem", [
    ({"hotels": None}, "unknown programme"),
    ({"esim": {"brand": "Yesim", "url": "http://yesim.tech"}}, "https"),
    ({"esim": {"brand": "Yesim", "url": "https://yesim.tech/?marker=424242"}}, "marker"),
    ({"activities": {"brand": "Tiqets", "url": "https://tiqets.com",
                     "destinations": {"paris": "https://tiqets.com/paris"}}}, "city code"),
])
def test_programme_config_takes_known_blocks_and_brand_pages_only(programmes, problem):
    with pytest.raises(ValidationError, match=problem):
        AffiliateConfig(programmes=programmes)


def test_the_repos_config_connects_esim_and_activities_and_no_insurance_yet():
    aff = AppConfig.model_validate(yaml.safe_load((REPO / "config.yaml").read_text("utf-8"))).affiliate
    assert aff.programme("esim").brand == "Yesim" and aff.programme("activities").brand == "Tiqets"
    assert aff.programme("insurance") is None


def test_committed_fixtures_carry_the_affiliate_blocks_of_the_fixture_content():
    """contract/site/v1/fixtures/affiliates.json and labels.json's disclosure.affiliate were added
    by hand (D37, like D36's post_url): they must be what `export fixtures` would write for the
    repo's config and fixture content (labels.json holds no database data at all)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init(conn)
    export = site_data.build_export(Context(root=REPO), conn, new_links=False, fixture=True)
    fixtures = REPO / "contract" / "site" / "v1" / "fixtures"
    labels = json.loads((fixtures / "labels.json").read_text("utf-8"))
    assert labels == export.files["labels.json"]
    assert labels["disclosure"]["affiliate"].startswith("Publicidade: esta ligação é um link de afiliado")
    committed = json.loads((fixtures / "affiliates.json").read_text("utf-8"))
    assert committed == export.files["affiliates.json"]
    assert {(lk["article"], lk["programme"]) for lk in committed["links"]} == {
        ("itineraries/paris-em-3-dias", "esim"), ("itineraries/paris-em-3-dias", "activities")}
    meta = json.loads((fixtures / "meta.json").read_text("utf-8"))
    assert meta["files"]["affiliates"] == "affiliates.json"


def test_fixture_data_links_the_test_only_articles_to_placeholders(ctx):  # noqa: F811
    configure(ctx, PROGRAMMES)
    write_article(ctx, "itineraries", "teste", fixture_copy(ITINERARY), folder="test/fixtures/content")
    conn = pipeline.open_db(ctx)
    doc = site_data.build_export(ctx, conn, new_links=False, fixture=True).files["affiliates.json"]
    assert doc["links"] == [
        {"article": "itineraries/teste", "programme": p, "url": f"{site_data.FIXTURE_LINK}roteiro-teste"}
        for p in ("activities", "esim")]

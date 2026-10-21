"""Brand switch (D19): per-channel Travelpayouts Projects, final domain, redirects, noindex."""

import json

import pytest
import yaml
import respx
from pydantic import ValidationError

from escapadinha import pipeline, site_data
from escapadinha.affiliate import API_URL as LINKS_URL
from escapadinha.config import AffiliateConfig, SiteConfig
from escapadinha.storage import db
from escapadinha.website.redirects import (MAX_STATIC_REDIRECTS, headers_text, plan_redirects,
                                           update_history)
from test_pipeline import REPO, ctx  # noqa: F401
from test_website import approved_deal


def link_requests():
    return [json.loads(c.request.content) for c in respx.calls if str(c.request.url) == LINKS_URL]


# --- config -------------------------------------------------------------------------

def test_repo_config_has_final_domain_and_channel_projects(ctx):
    cfg = ctx.config
    assert cfg.brand.name == "Ponto Nómada"
    assert cfg.brand.instagram_url == f"https://www.instagram.com/{cfg.brand.handle.lstrip('@')}/"
    assert cfg.affiliate.project_for("instagram") == 584711
    assert yaml.safe_load((REPO / "config.yaml").read_text("utf-8"))["affiliate"]["projects"]["website"] == 585209
    assert cfg.site.domain == "pontonomada.pt"
    assert "ondestaanocas.pages.dev" in cfg.site.legacy_hosts
    assert cfg.site.on_final_domain and cfg.site.base_url == "https://pontonomada.pt"


@pytest.mark.parametrize("raw, instagram, website", [
    ({"project_id": 584711}, 584711, 584711),                                  # old config files
    ({"projects": {"instagram": 1}}, 1, 1),
    ({"projects": {"instagram": 1, "website": None}}, 1, 1),
    ({"projects": {"instagram": 1, "website": 2}}, 1, 2),
    ({"project_id": 9, "projects": {"website": 2}}, 9, 2),
    ({}, None, None),
])
def test_project_per_channel_with_fallbacks(raw, instagram, website):
    aff = AffiliateConfig.model_validate(raw)
    assert aff.project_for("instagram") == instagram
    assert aff.project_for("website") == website


def test_unknown_channel_is_a_config_error():
    with pytest.raises(ValidationError, match="tiktok"):
        AffiliateConfig.model_validate({"projects": {"tiktok": 1}})


def test_site_config_hosts_and_domain():
    site = SiteConfig(base_url="https://ondestaanocas.pages.dev/", domain="https://PontoNomada.pt",
                      legacy_hosts=["https://ondestaanocas.pages.dev/", "www.pontonomada.pt"])
    assert site.base_url == "https://ondestaanocas.pages.dev" and site.domain == "pontonomada.pt"
    assert not site.on_final_domain
    assert site.retired_hosts == ["www.pontonomada.pt"]   # the current host is never noindexed
    moved = site.model_copy(update={"base_url": "https://pontonomada.pt"})
    assert moved.on_final_domain
    assert moved.retired_hosts == ["ondestaanocas.pages.dev", "www.pontonomada.pt"]
    with pytest.raises(ValidationError, match="https"):
        SiteConfig(base_url="http://pontonomada.pt")
    with pytest.raises(ValidationError, match="source"):
        SiteConfig(redirects={"old": "/new/"})


# --- _redirects / _headers rules ---------------------------------------------------

PAGES = {"page:/": "/", "deal:7": "/promos/7-lisboa-londres/", "route:LIS-LON": "/voos/lisboa-londres/"}


def test_moved_pages_redirect_from_every_old_path():
    history = {"deal:7": ["/promos/7-lisboa-londres-old/", "/promos/7-lisboa-londres/"],
               "route:LIS-PAR": ["/voos/lisboa-paris/"]}                # route removed: no rule
    plan = plan_redirects(PAGES, history, extra={}, aliases={})
    assert plan.rules == [("/promos/7-lisboa-londres-old", "/promos/7-lisboa-londres/"),
                          ("/promos/7-lisboa-londres-old/", "/promos/7-lisboa-londres/")]
    assert plan.text().splitlines()[1] == "/promos/7-lisboa-londres-old /promos/7-lisboa-londres/ 301"


def test_rules_never_shadow_a_page():
    """Pages redirects win over files, so a rule on a live path would hide that page."""
    extra = {"/voos/lisboa-londres/": "/", "/voos/lisboa-londres": "/", "/antigo/": "/sobre/"}
    history = {"route:LIS-LON": ["/voos/lisboa-londres/"], "deal:7": ["/voos/lisboa-londres/"]}
    plan = plan_redirects(PAGES, history, extra=extra, aliases={"/": "/promos/7-lisboa-londres/"})
    assert plan.rules == [("/antigo/", "/sobre/")]
    assert len(plan.skipped) == 2 and all("is a page" in s for s in plan.skipped)


def test_short_deal_alias_and_limit():
    aliases = {f"/promos/{i}": f"/promos/{i}-x/" for i in range(MAX_STATIC_REDIRECTS)}
    plan = plan_redirects({}, {}, extra={}, aliases=aliases)
    assert plan.rules[:2] == [("/promos/0", "/promos/0-x/"), ("/promos/0/", "/promos/0-x/")]
    assert len(plan.rules) == MAX_STATIC_REDIRECTS
    assert len(plan.skipped) == MAX_STATIC_REDIRECTS and "limit" in plan.skipped[0]


def test_history_keeps_every_published_path():
    history = update_history({"deal:7": ["/promos/7-a/"]}, {"deal:7": "/promos/7-b/", "page:/": "/"})
    assert history == {"deal:7": ["/promos/7-a/", "/promos/7-b/"], "page:/": ["/"]}


def test_headers_noindex_only_hosts_that_are_not_the_site():
    before = SiteConfig(base_url="https://ondestaanocas.pages.dev",
                        legacy_hosts=["ondestaanocas.pages.dev"])
    text = headers_text(before)
    assert "https://ondestaanocas.pages.dev/*" not in text          # still the live host
    assert "https://:version.ondestaanocas.pages.dev/*\n  X-Robots-Tag: noindex" in text
    after = before.model_copy(update={"base_url": "https://pontonomada.pt"})
    text = headers_text(after)
    assert "https://ondestaanocas.pages.dev/*\n  X-Robots-Tag: noindex" in text
    assert "pontonomada.pt/*" not in text


# --- the site's booking links ------------------------------------------------------------

def booking_link(ctx, conn, out, deal_id):
    """The promotion's booking link in a fresh site data export (what its page's button opens)."""
    export = site_data.export_site_data(ctx, conn, out)
    return {p["id"]: p["booking_link"]
            for p in export.files["promotions.json"]["promotions"]}[deal_id]


@respx.mock
def test_site_uses_instagram_link_until_a_website_project_exists(ctx, tmp_path):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    link = booking_link(ctx, conn, tmp_path, deal_id)
    deal, _ = db.get_deal(conn, deal_id)
    assert link == deal.affiliate_url
    assert not [l for r in link_requests() for l in r["links"]              # no site-deal link
                if l["sub_id"].startswith("site-deal-")]
    assert {r["trs"] for r in link_requests()} == {584711}


@respx.mock
def test_site_uses_its_own_project_and_caches_links(ctx, tmp_path):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    ctx.config.affiliate.projects["website"] = 700001
    link = booking_link(ctx, conn, tmp_path, deal_id)
    sent = [r for r in link_requests() if r["trs"] == 700001][-1]
    assert sent["links"][0]["sub_id"] == f"site-deal-{deal_id}"
    assert link == f"https://aviasales.tpo.lu/site-deal-{deal_id}" and "marker=" not in link
    deal, _ = db.get_deal(conn, deal_id)
    assert deal.affiliate_url == f"https://aviasales.tpo.lu/deal-{deal_id}"   # Instagram's untouched
    count = len([r for r in link_requests() if r["trs"] == 700001])
    booking_link(ctx, conn, tmp_path, deal_id)
    assert len([r for r in link_requests() if r["trs"] == 700001]) == count    # cached per Project


@respx.mock
def test_failed_website_link_falls_back_to_the_deals_tracked_link(ctx, tmp_path):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    ctx.config.affiliate.projects["website"] = 700001
    ctx.secrets.travelpayouts_marker = ""            # PartnerLinksClient refuses: no request
    deal, _ = db.get_deal(conn, deal_id)
    assert booking_link(ctx, conn, tmp_path, deal_id) == deal.affiliate_url
    entry = pipeline.site_links(ctx, conn)["700001"][str(deal_id)]
    assert entry["url"] is None and "MARKER" in entry["error"]          # recorded, not hidden
    ctx.secrets.travelpayouts_marker = "424242"      # retried on the next export
    assert booking_link(ctx, conn, tmp_path, deal_id) == f"https://aviasales.tpo.lu/site-deal-{deal_id}"

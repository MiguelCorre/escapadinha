"""Brand switch (D19): per-channel Travelpayouts Projects, final domain, redirects, noindex."""

import json

import pytest
import respx
from pydantic import ValidationError

from escapadinha import pipeline
from escapadinha.affiliate import API_URL as LINKS_URL
from escapadinha.config import AffiliateConfig, SiteConfig
from escapadinha.storage import db
from escapadinha.website import build_site
from escapadinha.website.redirects import (MAX_STATIC_REDIRECTS, headers_text, plan_redirects,
                                           update_history)
from test_pipeline import ctx  # noqa: F401
from test_website import approved_deal, html


def link_requests():
    return [json.loads(c.request.content) for c in respx.calls if str(c.request.url) == LINKS_URL]


# --- config -------------------------------------------------------------------------

def test_repo_config_has_final_domain_and_channel_projects(ctx):
    cfg = ctx.config
    assert cfg.brand.name == "Ponto Nómada"
    assert cfg.brand.instagram_url == f"https://www.instagram.com/{cfg.brand.handle.lstrip('@')}/"
    assert cfg.affiliate.project_for("instagram") == 584711
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


# --- site build ------------------------------------------------------------------------

@respx.mock
def test_site_uses_instagram_link_until_a_website_project_exists(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    before = len(link_requests())
    build_site(ctx, conn)
    deal, _ = db.get_deal(conn, deal_id)
    assert link_requests()[-1]["trs"] == 584711 and len(link_requests()) == before
    assert f'href="{deal.affiliate_url}"' in html(ctx, f"promos/{deal_id}-lisboa-londres/index.html")


@respx.mock
def test_site_uses_its_own_project_and_caches_links(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    ctx.config.affiliate.projects["website"] = 700001
    build_site(ctx, conn)
    sent = link_requests()[-1]
    assert sent["trs"] == 700001 and sent["links"][0]["sub_id"] == f"site-deal-{deal_id}"
    page = html(ctx, f"promos/{deal_id}-lisboa-londres/index.html")
    assert f'href="https://aviasales.tpo.lu/site-deal-{deal_id}" rel="sponsored' in page
    assert "marker=" not in page
    deal, _ = db.get_deal(conn, deal_id)
    assert deal.affiliate_url == f"https://aviasales.tpo.lu/deal-{deal_id}"   # Instagram's untouched
    count = len(link_requests())
    build_site(ctx, conn)
    assert len(link_requests()) == count                                    # cached per Project


@respx.mock
def test_failed_website_link_falls_back_to_the_deals_tracked_link(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    ctx.config.affiliate.projects["website"] = 700001
    ctx.secrets.travelpayouts_marker = ""            # PartnerLinksClient refuses: no request
    build_site(ctx, conn)
    deal, _ = db.get_deal(conn, deal_id)
    assert f'href="{deal.affiliate_url}"' in html(ctx, f"promos/{deal_id}-lisboa-londres/index.html")
    cache = json.loads((ctx.db_path.parent / "site_links.json").read_text("utf-8"))
    entry = cache["700001"][str(deal_id)]
    assert entry["url"] is None and "MARKER" in entry["error"]          # recorded, not hidden
    ctx.secrets.travelpayouts_marker = "424242"      # retried on the next build
    build_site(ctx, conn)
    assert f"site-deal-{deal_id}" in html(ctx, f"promos/{deal_id}-lisboa-londres/index.html")


@respx.mock
def test_build_writes_redirects_and_old_paths_keep_working(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved_deal(ctx, conn)
    summary = build_site(ctx, conn)
    rules = html(ctx, "_redirects")
    assert f"/promos/{deal_id} /promos/{deal_id}-lisboa-londres/ 301" in rules
    assert summary["skipped_redirects"] == []
    conn.execute("UPDATE routes SET city_pt = 'Londres Centro' "      # slug changes
                 "WHERE origin = 'LIS' AND destination = 'LON'")
    conn.commit()
    build_site(ctx, conn)
    rules = html(ctx, "_redirects")
    assert (f"/promos/{deal_id}-lisboa-londres/ /promos/{deal_id}-lisboa-londres-centro/ 301"
            in rules)
    assert "/voos/lisboa-londres/ /voos/lisboa-londres-centro/ 301" in rules
    assert (ctx.site_dir / f"promos/{deal_id}-lisboa-londres-centro/index.html").exists()
    assert "X-Robots-Tag: noindex" in html(ctx, "_headers")


def test_switching_base_url_moves_canonicals_and_noindexes_the_old_host(ctx):
    conn = pipeline.open_db(ctx)
    ctx.config.site.base_url = "https://pontonomada.pt"
    build_site(ctx, conn)
    assert '<link rel="canonical" href="https://pontonomada.pt/">' in html(ctx, "index.html")
    assert "Sitemap: https://pontonomada.pt/sitemap.xml" in html(ctx, "robots.txt")
    assert "https://ondestaanocas.pages.dev/*\n  X-Robots-Tag: noindex" in html(ctx, "_headers")

"""Review decisions as events (D26): written by the CLI / review page / review Function,
applied by the pipeline, exported as a snapshot. Through the pipeline seam with the local store."""

import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest
import respx

from escapadinha import pipeline
from escapadinha.collector.travelpayouts import API_URL
from escapadinha.presentation import DISCLOSURE
from escapadinha.review import ReviewError
from escapadinha.storage import db
from test_web_build import npm  # noqa: F401
from test_pipeline import ctx, mock_api, mock_links  # noqa: F401
from test_review import price_api, rendered_deal

CONTRACT = Path(__file__).parent.parent / "contract" / "review" / "v1"
PENDING, ARCHIVE = "review/events/pending/", "review/events/archive/"


def schema(name: str) -> dict:
    return json.loads((CONTRACT / f"{name}.schema.json").read_text("utf-8"))


def validate(name: str, data: dict) -> None:
    from referencing import Registry, Resource
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in (schema("event"), schema("snapshot")))
    validator = jsonschema.Draft202012Validator(schema(name), registry=registry,
                                                format_checker=jsonschema.FormatChecker())
    validator.validate(data)


def test_schemas_are_valid_draft_2020_12():
    for name in ("event", "snapshot"):
        jsonschema.Draft202012Validator.check_schema(schema(name))


def test_only_the_applier_writes_review_decisions():
    """Contract (D26): approve / reject / published reach the database only through the applier."""
    src = Path(__file__).parent.parent / "src" / "escapadinha"
    writers = {p.name for p in src.rglob("*.py")
               if "settle_review_event(" in p.read_text("utf-8") or "record_review(" in p.read_text("utf-8")}
    assert writers == {"db.py", "review_events.py"}


def test_event_schema_matches_what_the_applier_accepts():
    from escapadinha.review_events import Event
    check = {"valid": True, "price_eur": 58, "reason": "continua a 58 €",
             "checked_at": "2026-10-13T09:00:00.000Z"}           # JavaScript's toISOString()
    good = [raw_event(1), raw_event(1, "approve", live_check=check),
            raw_event(1, "published", post_url="https://www.instagram.com/p/x/")]
    for event in good:
        validate("event", event)
        Event.from_json(event)
    bad = [raw_event(1, "delete"), raw_event(0), raw_event(1, id="not-a-uuid"),
           raw_event(1, actor=""), raw_event(1, version=2), raw_event(1, created_at="ontem")]
    for event in bad:
        with pytest.raises(jsonschema.ValidationError):
            validate("event", event)
        with pytest.raises(ValueError):
            Event.from_json(event)
    # Shape-valid but refused when applied (needs the deal's state): the schema catches these too.
    for event in (raw_event(1, "approve"), raw_event(1, "approve", live_check={**check, "valid": False}),
                  raw_event(1, post_url="https://x")):
        with pytest.raises(jsonschema.ValidationError):
            validate("event", event)


def archived(store) -> list[dict]:
    return [json.loads(store.get(k)) for k in store.list(ARCHIVE)]


@respx.mock
def test_local_approve_writes_an_event_and_applies_it(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    decision = pipeline.approve(ctx, conn, deal_id, note="bom deal", actor="cli:test")
    assert decision.deal.status == "approved" and decision.deal.review_note == "bom deal"
    assert decision.outcome is not None and decision.outcome.applied
    store = ctx.object_store
    assert store.list(PENDING) == []                     # local database: settled at once
    [record] = archived(store)
    assert record["outcome"] == "applied" and record["reason"] is None
    event = record["event"]
    validate("event", event)
    assert (event["type"], event["deal_id"], event["actor"], event["note"]) == \
        ("approve", deal_id, "cli:test", "bom deal")
    assert event["live_check"]["valid"] and event["live_check"]["price_eur"] == 58


@respx.mock
def test_approve_with_a_moved_price_is_refused_and_writes_nothing(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    runs = conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0]
    price_api(80)
    with pytest.raises(ReviewError, match="o preço subiu para 80 €"):
        pipeline.approve(ctx, conn, deal_id, actor="cli:test")
    assert ctx.object_store.list("review/") == []
    deal = db.get_deal(conn, deal_id)[0]
    assert deal.status == "rendered" and deal.last_checked_at is None   # the run's recheck expires it
    assert conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0] == runs


@pytest.fixture
def remote(ctx, monkeypatch):
    """R2 'configured': the bucket is a local directory, the database is only durable when a
    run pushes it."""
    from escapadinha.config import Context
    from escapadinha.storage.objects import LocalObjectStore
    bucket = LocalObjectStore(ctx.root / "bucket")
    monkeypatch.setattr(Context, "remote_store", property(lambda self: True))
    monkeypatch.setattr(Context, "object_store", property(lambda self: bucket))
    return ctx, bucket


def copy_db(conn, path):
    """The database as a run would have pulled it now."""
    target = db.connect(path)
    conn.backup(target)
    return target


@respx.mock
def test_with_r2_an_event_waits_for_the_run_and_survives_a_run_that_never_pushed(remote, tmp_path):
    ctx, store = remote
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    decision = pipeline.approve(ctx, conn, deal_id, actor="miguel@example.com")
    assert decision.outcome is None and decision.deal.status == "rendered"
    assert [e.id for e in pipeline.pending_decisions(ctx, conn)] == [decision.event.id]
    with pytest.raises(ReviewError, match="decisão pendente"):
        pipeline.reject(ctx, conn, deal_id, actor="cli:test")
    pulled_before = copy_db(conn, tmp_path / "before.db")

    [outcome] = pipeline.apply_review_events(ctx, conn)
    assert outcome.applied and (outcome.status_before, outcome.status_after) == ("rendered", "approved")
    assert db.get_deal(conn, deal_id)[0].status == "approved"
    assert pipeline.pending_decisions(ctx, conn) == []         # applied to this database...
    assert store.list(PENDING) == [decision.event.key]         # ...but kept until it is pushed

    # That run died before pushing: the next one starts from the old database and applies again.
    [again] = pipeline.apply_review_events(ctx, pulled_before)
    assert again.applied and db.get_deal(pulled_before, deal_id)[0].status == "approved"

    # A run starting from a database that has the outcome only archives the event.
    assert pipeline.apply_review_events(ctx, conn) == []
    assert store.list(PENDING) == []
    [record] = archived(store)
    assert record["outcome"] == "applied" and record["event"]["id"] == decision.event.id


@respx.mock
def test_review_page_with_r2_writes_events_and_lists_them_as_pending(remote):
    from fastapi.testclient import TestClient
    from escapadinha.web import create_app
    ctx, store = remote
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    client = TestClient(create_app(ctx))
    price_api(58)
    r = client.post(f"/api/deals/{deal_id}/approve", json={"note": "bom"})
    assert r.status_code == 200 and r.json()["check"]["valid"]
    assert r.json()["decision"]["outcome"] == "pending"
    [d] = client.get("/api/deals", params={"tab": "queue"}).json()["deals"]
    assert d["status"] == "rendered"
    [p] = d["pending"]
    assert (p["type"], p["note"]) == ("approve", "bom") and p["actor"].startswith("review-page:")
    again = client.post(f"/api/deals/{deal_id}/reject", json={})
    assert again.status_code == 409 and "decisão pendente" in again.json()["detail"]
    assert len(store.list(PENDING)) == 1


@respx.mock
def test_cli_with_r2_writes_events_and_prints_the_pending_state(remote, monkeypatch):
    from typer.testing import CliRunner
    from escapadinha import cli
    ctx, store = remote
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    result = CliRunner().invoke(cli.app, ["deal", "approve", str(deal_id), "--note", "bom"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "preço confirmado" in out and "próxima execução" in out
    assert f"1 decisão pendente: deal {deal_id}: aprovar" in out
    assert db.get_deal(conn, deal_id)[0].status == "rendered"
    [key] = store.list(PENDING)
    validate("event", json.loads(store.get(key)))


def test_with_r2_a_deal_missing_from_the_local_copy_is_a_review_error(remote):
    from fastapi.testclient import TestClient
    from escapadinha.web import create_app
    ctx, store = remote
    conn = pipeline.open_db(ctx)
    for decide in (pipeline.reject, pipeline.mark_published):
        with pytest.raises(ReviewError, match="O deal 999 não existe"):
            decide(ctx, conn, 999, actor="cli:test")
    with pytest.raises(ReviewError, match="O deal 999 não existe"):
        pipeline.approve(ctx, conn, 999, actor="cli:test")
    r = TestClient(create_app(ctx)).post("/api/deals/999/reject", json={})
    assert r.status_code == 404 and "O deal 999 não existe" in r.json()["detail"]
    assert store.list(PENDING) == []


@respx.mock
def test_with_r2_decisions_are_refused_while_the_bucket_has_a_newer_database(remote, tmp_path):
    from escapadinha.storage import sync
    ctx, store = remote
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    quiet = dict(log=lambda _: None)
    sync.push(store, ctx.db_path, ctx.sync_state_path, owner="pc", **quiet)     # generation 1
    pipeline.reject(ctx, conn, deal_id, actor="cli:test")       # this copy is current: written
    [first] = store.list(PENDING)
    store.delete(first)

    other = tmp_path / "runner" / "escapadinha.db"              # a run pushes generation 2
    copy_db(conn, other).close()
    sync.push(store, other, other.with_suffix(".sync.json"), owner="run", force=True, **quiet)
    price_api(58)
    for decide in (pipeline.approve, pipeline.reject, pipeline.mark_published):
        with pytest.raises(ReviewError, match="escapadinha store pull"):
            decide(ctx, conn, deal_id, actor="cli:test")
    assert store.list(PENDING) == []

    conn.close()
    sync.pull(store, ctx.db_path, ctx.sync_state_path, **quiet)
    conn = db.connect(ctx.db_path)
    assert pipeline.reject(ctx, conn, deal_id, actor="cli:test").outcome is None   # pending
    assert len(store.list(PENDING)) == 1


@respx.mock
def test_with_r2_deal_check_only_reports_and_the_run_expires_the_deal(remote, monkeypatch):
    """The local copy is not authoritative with R2 (D26): `deal check` stores nothing and
    changes no status; the next run's recheck expires the deal. (Local mode: test_review.)"""
    from typer.testing import CliRunner
    from escapadinha import cli
    ctx, store = remote
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    runs = conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0]
    archives = store.list("archive/")
    price_api(80)
    deal, check = pipeline.live_check(ctx, conn, deal_id)
    assert not check.valid and check.reason == "o preço subiu para 80 €"
    assert deal.status == "rendered" and deal.last_checked_at is None
    assert conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0] == runs
    assert not list(ctx.output_dir.rglob("EXPIRADO.txt")) and store.list("archive/") == archives

    result = CliRunner().invoke(cli.app, ["deal", "check", str(deal_id)])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "o preço subiu para 80 €" in out and "a próxima recolha expira o deal" in out
    assert db.get_deal(conn, deal_id)[0].status == "rendered"


@respx.mock
def test_cli_without_r2_applies_the_decision_at_once(ctx, monkeypatch):
    from typer.testing import CliRunner
    from escapadinha import cli
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    result = CliRunner().invoke(cli.app, ["deal", "reject", str(deal_id), "--note", "datas fracas"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert f"deal {deal_id}: rejeitado" in out and "Nenhuma decisão pendente" in out
    deal = db.get_deal(conn, deal_id)[0]
    assert deal.status == "rejected" and deal.review_note == "datas fracas"


@respx.mock
def test_collection_live_check_and_snapshot_ask_the_same_query(remote):
    """D39: the run that found the deal, the approval's live check and the snapshot the review
    Function asks with all send one query for the deal's route-month: nonstop fares only on a
    direct-only route, so the recheck never loses a nonstop fare to a cheaper one with a stop."""
    ctx, _ = remote
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    pipeline.approve(ctx, conn, deal_id, actor="cli:test")
    [d] = pipeline.export_review_snapshot(ctx, conn)["queue"]
    query = {k: str(v) for k, v in d["live_check"]["query"].items()}
    assert query["direct"] == "true" and d["live_check"]["rules"]["direct_only"] is True

    asked = [dict(c.request.url.params) for c in respx.calls
             if str(c.request.url).startswith(f"{API_URL}?")]
    month = [p for p in asked if (p["origin"], p["destination"], p["departure_at"])
             == ("LIS", "LON", d["departure_date"][:7])]
    assert len(month) == 2                         # the collection's request, the live check's
    assert month == [query, query]


@respx.mock
def test_snapshot_follows_a_deal_from_queue_to_published(remote):
    from test_website import real_slides
    ctx, store = remote
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    real_slides(conn, deal_id)
    base = ctx.config.site.base_url
    price_api(58)
    approval = pipeline.approve(ctx, conn, deal_id, note="bom", actor="miguel@example.com")

    snap = pipeline.export_review_snapshot(ctx, conn)
    assert json.loads(store.get("review/snapshot.json")) == snap
    validate("snapshot", snap)
    [d] = snap["queue"]
    assert snap["approved"] == snap["published"] == snap["closed"] == []
    assert (d["id"], d["status"], d["price_eur"], d["price"]) == (deal_id, "rendered", 58, "58 €")
    assert d["headline"] == "Lisboa → Londres" and d["caption"] == "legenda de teste"
    assert d["whatsapp_text"] is None and d["page_url"] is None
    # Not public yet: slides only in the store, for the review page behind Access.
    assert [s["key"] for s in d["slides"]] == [f"review/slides/{deal_id}/slide_0{n}.webp"
                                               for n in (1, 2, 3)]
    assert all(s["url"] is None for s in d["slides"])
    assert all(store.get(s["key"])[:4] == b"RIFF" for s in d["slides"])
    lc = d["live_check"]
    assert lc["query"]["origin"] == "LIS" and lc["query"]["destination"] == "LON"
    assert lc["query"]["departure_at"] == d["departure_date"][:7]
    assert lc["rules"]["direct_only"] is True and lc["last_checked_at"] is None
    # The observation's stop counts, for the Function's stop limit (D29).
    obs = db.get_deal(conn, deal_id)[1]
    assert (d["transfers"], d["return_transfers"]) == (obs.transfers, obs.return_transfers) == (0, 0)
    [p] = snap["pending_events"]
    assert p == approval.event.to_json()

    pipeline.apply_review_events(ctx, conn)
    snap = pipeline.export_review_snapshot(ctx, conn)
    validate("snapshot", snap)
    assert snap["queue"] == [] and snap["pending_events"] == []
    [d] = snap["approved"]
    assert d["page_url"] == f"{base}/promos/{deal_id}-lisboa-londres/"
    # Approved: the WhatsApp text to paste, with the deal's stored partner link (D32).
    deal = db.get_deal(conn, deal_id)[0]
    assert d["whatsapp_text"].startswith("✈️ Lisboa → Londres desde 58 € ida e volta")
    assert f"👉 {deal.affiliate_url}" in d["whatsapp_text"]
    assert DISCLOSURE in d["whatsapp_text"]
    assert [s["url"] for s in d["slides"]] == [f"{base}/img/promos/{deal_id}/slide_0{n}.webp"
                                               for n in (1, 2, 3)]
    [o] = snap["recent_outcomes"]
    assert (o["event_id"], o["outcome"], o["status_after"]) == (approval.event.id, "applied", "approved")

    pipeline.mark_published(ctx, conn, deal_id, "https://www.instagram.com/p/x/", actor="cli:test")
    pipeline.apply_review_events(ctx, conn)
    snap = pipeline.export_review_snapshot(ctx, conn)
    validate("snapshot", snap)
    [d] = snap["published"]
    assert d["post_url"] == "https://www.instagram.com/p/x/" and d["published_at"]
    assert DISCLOSURE in d["whatsapp_text"]
    assert store.list("review/slides/") == []          # no longer reviewable: store copies go


@respx.mock
def test_run_applies_events_first_and_exports_the_snapshot_last(ctx, monkeypatch, npm):
    from typer.testing import CliRunner
    from escapadinha import cli
    from test_web_build import web_package
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    web_package(ctx.root)                              # the full path builds the site (npm faked)
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    db.set_meta(conn, pipeline.DISCOVERED_AT, db.utcnow().isoformat())   # no discovery this run
    put_raw(ctx.object_store, "20261013T090000Z-x.json", raw_event(deal_id, note="via telemóvel"))
    mock_api()
    mock_links()
    result = CliRunner().invoke(cli.app, ["run", "--no-render"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert f"decisão rejeitar deal {deal_id}: aplicada" in out
    assert out.index("decisão rejeitar") < out.index("Run #")         # before the collection
    snap = json.loads(ctx.object_store.get("review/snapshot.json"))
    validate("snapshot", snap)
    assert [d["id"] for d in snap["closed"]] == [deal_id] and snap["queue"] == []
    assert "Review snapshot: 0 por rever" in out


@respx.mock
def test_snapshot_on_a_runner_reads_rendered_slides_from_the_store(remote):
    import shutil
    from test_website import real_slides
    ctx, store = remote
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    real_slides(conn, deal_id)
    folder = ctx.output_dir / "2026-10-12" / f"deal-LIS-LON-{deal_id}"
    pipeline.output_files(ctx).put_tree(folder)      # rendered elsewhere (D25)
    shutil.rmtree(ctx.output_dir)                    # a fresh runner has no output/

    [d] = pipeline.export_review_snapshot(ctx, conn)["queue"]
    assert d["caption"] == "legenda de teste"
    assert [s["key"] for s in d["slides"]] == [f"review/slides/{deal_id}/slide_0{n}.webp"
                                               for n in (1, 2, 3)]


class FlakyDelete:
    """A store whose next delete fails (e.g. the network drops after the archive put)."""

    def __init__(self, store):
        self.store, self.fail = store, True

    def __getattr__(self, name):
        return getattr(self.store, name)

    def delete(self, key):
        if self.fail:
            self.fail = False
            raise ConnectionError("network down")
        self.store.delete(key)


@respx.mock
def test_applying_an_event_twice_is_a_no_op(ctx, monkeypatch):
    from escapadinha.config import Context
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    pipeline.approve(ctx, conn, deal_id, actor="cli:test")
    store = ctx.object_store
    flaky = FlakyDelete(store)
    monkeypatch.setattr(Context, "object_store", property(lambda self: flaky))

    decision = pipeline.mark_published(ctx, conn, deal_id, "https://www.instagram.com/p/x/",
                                       actor="cli:test")
    assert decision.outcome.applied                            # applied although the delete failed
    published = db.get_deal(conn, deal_id)[0]
    assert published.status == "published"
    assert store.list(PENDING) == [decision.event.key]          # archived, pending left behind

    assert pipeline.apply_review_events(ctx, conn) == []        # nothing applied again
    store.put(decision.event.key, json.dumps(decision.event.to_json()).encode())   # re-delivered
    assert pipeline.apply_review_events(ctx, conn) == []
    assert store.list(PENDING) == []
    assert db.get_deal(conn, deal_id)[0] == published
    assert [r["outcome"] for r in archived(store)] == ["applied", "applied"]   # approve, published


def raw_event(deal_id, type="reject", **extra):
    import uuid
    body = {"version": 1, "id": str(uuid.uuid4()), "type": type, "deal_id": deal_id,
            "created_at": "2026-10-13T09:00:00Z", "actor": "miguel@example.com", "note": None,
            "post_url": None, "live_check": None}
    return {**body, **extra}


def put_raw(store, name, body):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    store.put(f"{PENDING}{name}", data)


@respx.mock
def test_invalid_events_are_archived_with_a_reason_and_never_stop_the_run(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    store = ctx.object_store
    put_raw(store, "20261013T090000Z-a.json", raw_event(deal_id, "approve"))  # no live check
    put_raw(store, "20261013T090001Z-b.json", raw_event(deal_id, "published"))  # not approved
    put_raw(store, "20261013T090002Z-c.json", raw_event(999))                # no such deal
    put_raw(store, "20261013T090003Z-d.json", raw_event(deal_id, "delete"))
    put_raw(store, "20261013T090004Z-e.json", b"{not json")
    put_raw(store, "20261013T090005Z-f.json", raw_event(deal_id, note="datas fracas"))
    put_raw(store, "20261013T090006Z-g.json", raw_event(deal_id))            # already rejected

    outcomes = pipeline.apply_review_events(ctx, conn)
    assert [o.outcome for o in outcomes] == ["refused", "refused", "refused", "malformed",
                                              "malformed", "applied", "refused"]
    reasons = [o.reason for o in outcomes]
    assert "verificação de preço" in reasons[0]
    assert "'por rever' para 'publicado'" in reasons[1]
    assert "999 não existe" in reasons[2]
    assert "desconhecido" in reasons[3] and "JSON" in reasons[4]
    assert "'rejeitado' para 'rejeitado'" in reasons[6]
    deal = db.get_deal(conn, deal_id)[0]
    assert deal.status == "rejected" and deal.review_note == "datas fracas"
    assert store.list(PENDING) == []
    assert len(store.list(ARCHIVE)) == 7
    assert all(k.startswith(f"{ARCHIVE}2026-10/") for k in store.list(ARCHIVE))


@respx.mock
def test_approve_events_older_than_the_limit_are_refused_others_never_expire(remote, tmp_path):
    """Miguel's rule (D26): an approval rests on a live check at most 24 h old when applied."""
    ctx, store = remote
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    now = db.utcnow().replace(microsecond=0)
    approval = pipeline.approve(ctx, conn, deal_id, actor="miguel@example.com", now=now)
    assert pipeline.export_review_snapshot(ctx, conn, now)["review_rules"] == \
        {"approve_max_age_hours": 24}

    within = copy_db(conn, tmp_path / "within.db")
    [ok] = pipeline.apply_review_events(ctx, within, now=now + timedelta(hours=23, minutes=59))
    assert ok.applied and db.get_deal(within, deal_id)[0].status == "approved"

    [late] = pipeline.apply_review_events(ctx, conn, now=now + timedelta(hours=24, seconds=1))
    assert (late.event_id, late.outcome) == (approval.event.id, "refused")
    assert late.reason == "Aprovação com mais de 24 h: verifica o preço outra vez."
    assert db.get_deal(conn, deal_id)[0].status == "rendered"
    pipeline.apply_review_events(ctx, conn, now=now + timedelta(hours=25))     # archives it
    [record] = archived(store)
    assert record["outcome"] == "refused" and record["event"]["id"] == approval.event.id

    # Reject (and published) carry no live check and never expire.
    rejection = pipeline.reject(ctx, conn, deal_id, "datas fracas", actor="cli:test", now=now)
    [later] = pipeline.apply_review_events(ctx, conn, now=now + timedelta(days=10))
    assert later.event_id == rejection.event.id and later.applied


@respx.mock
def test_the_approve_age_limit_comes_from_config(remote):
    ctx, _ = remote
    ctx.config.review.approve_max_age_hours = 2
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    now = db.utcnow().replace(microsecond=0)
    pipeline.approve(ctx, conn, deal_id, actor="cli:test", now=now)
    [late] = pipeline.apply_review_events(ctx, conn, now=now + timedelta(hours=3))
    assert late.reason == "Aprovação com mais de 2 h: verifica o preço outra vez."
    snap = pipeline.export_review_snapshot(ctx, conn, now)
    validate("snapshot", snap)
    assert snap["review_rules"] == {"approve_max_age_hours": 2}


@respx.mock
def test_a_fractional_approve_age_limit_reads_in_pt_pt(remote):
    ctx, _ = remote
    ctx.config.review.approve_max_age_hours = 1.5
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    price_api(58)
    now = db.utcnow().replace(microsecond=0)
    pipeline.approve(ctx, conn, deal_id, actor="cli:test", now=now)
    [late] = pipeline.apply_review_events(ctx, conn, now=now + timedelta(hours=2))
    assert late.reason == "Aprovação com mais de 1,5 h: verifica o preço outra vez."

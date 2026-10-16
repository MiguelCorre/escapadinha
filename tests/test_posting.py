"""Posting queue (D32): daily Instagram slots in Lisbon time, Telegram at once, a run step that
publishes due posts after re-verifying the promotion, the dry-run publisher, `queue list`,
and the WhatsApp text."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time, timezone

import pytest
import respx
import yaml

from escapadinha import pipeline, posting
from escapadinha.presentation import DISCLOSURE
from escapadinha.storage import db
from test_pipeline import ctx, mock_links  # noqa: F401
from test_review import rendered_deal
from test_web_build import npm  # noqa: F401

UTC = timezone.utc
SLOTS = [time(9), time(13), time(19)]


@pytest.fixture(autouse=True)
def dry_run_channels(request):
    """D32's queue rules are tested with both channels on the dry-run publisher, in this
    context and in the CLI's (config.yaml has `instagram: instagram` and `telegram: telegram`,
    which wait without their secrets: test_instagram.py, test_telegram.py)."""
    if "ctx" in request.fixturenames:
        ctx = request.getfixturevalue("ctx")
        dry = {channel: "dry-run" for channel in posting.CHANNELS}
        ctx.config.posting.publishers = dry
        path = ctx.root / "config.yaml"
        config = yaml.safe_load(path.read_text("utf-8"))
        config["posting"]["publishers"] = dry
        path.write_text(yaml.safe_dump(config, allow_unicode=True), "utf-8")


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def slot(now, taken=(), slots=SLOTS, cap=3):
    return posting.next_slot(now, list(taken), slots=slots, max_per_day=cap)


# --- slot allocation (pure, injected now) ---------------------------------------------------

def test_next_slot_is_the_next_daily_slot_in_lisbon_summer_time():
    # 2026-07-01 08:00 UTC = 09:00 Lisbon (WEST, UTC+1): the 09:00 slot is now, still free.
    assert slot(utc(2026, 7, 1, 8, 0)) == utc(2026, 7, 1, 8, 0)
    # A second later the 09:00 slot has passed: 13:00 Lisbon = 12:00 UTC.
    assert slot(utc(2026, 7, 1, 8, 0, 1)) == utc(2026, 7, 1, 12, 0)


def test_next_slot_in_winter_time():
    # 2026-12-01: Lisbon is UTC+0.
    assert slot(utc(2026, 12, 1, 10, 0)) == utc(2026, 12, 1, 13, 0)
    assert slot(utc(2026, 12, 1, 19, 30)) == utc(2026, 12, 2, 9, 0)


def test_taken_slots_are_skipped_and_the_daily_cap_moves_to_the_next_day():
    now = utc(2026, 12, 1, 7, 0)
    first = slot(now)
    second = slot(now, [first])
    third = slot(now, [first, second])
    fourth = slot(now, [first, second, third])
    assert [first, second, third, fourth] == [utc(2026, 12, 1, 9), utc(2026, 12, 1, 13),
                                              utc(2026, 12, 1, 19), utc(2026, 12, 2, 9)]


def test_a_cap_below_the_number_of_slots_limits_the_day():
    now = utc(2026, 12, 1, 7, 0)
    first = slot(now, cap=2)
    second = slot(now, [first], cap=2)
    assert slot(now, [first, second], cap=2) == utc(2026, 12, 2, 9)


def test_posts_already_made_today_count_against_the_cap():
    # 09:00 and 13:00 went out (published), cap 2: nothing more today even though 19:00 is free.
    taken = [utc(2026, 12, 1, 9), utc(2026, 12, 1, 13)]
    assert slot(utc(2026, 12, 1, 14), taken, cap=2) == utc(2026, 12, 2, 9)


def test_the_lisbon_day_not_the_utc_day_decides_today():
    # 2026-06-30 23:30 UTC is already 1 July 00:30 in Lisbon: today's 09:00 is the next slot.
    assert slot(utc(2026, 6, 30, 23, 30)) == utc(2026, 7, 1, 8, 0)
    # A cap reached on 1 July (Lisbon) is not reset by the UTC date.
    taken = [utc(2026, 7, 1, 8), utc(2026, 7, 1, 12), utc(2026, 7, 1, 18)]
    assert slot(utc(2026, 6, 30, 23, 30), taken) == utc(2026, 7, 2, 8)


def test_dst_starts_on_the_last_sunday_of_march():
    # Saturday 28 March 2026 is winter time; on Sunday 29 March clocks go 01:00 -> 02:00.
    assert slot(utc(2026, 3, 28, 19, 30)) == utc(2026, 3, 29, 8, 0)    # 09:00 WEST
    taken = [utc(2026, 3, 29, 8), utc(2026, 3, 29, 12)]
    assert slot(utc(2026, 3, 28, 19, 30), taken) == utc(2026, 3, 29, 18, 0)


def test_dst_ends_on_the_last_sunday_of_october():
    # 2026-10-24 23:30 UTC = Sunday 25 October 00:30 WEST; at 02:00 clocks go back to 01:00.
    assert slot(utc(2026, 10, 24, 23, 30)) == utc(2026, 10, 25, 9, 0)   # 09:00 WET
    assert slot(utc(2026, 10, 24, 17, 59)) == utc(2026, 10, 24, 18, 0)  # 19:00 WEST, Saturday


def test_slots_inside_the_clock_change_hour():
    # 01:30 does not exist on 29 March: it is read with the winter offset (01:30 UTC = 02:30).
    assert slot(utc(2026, 3, 29, 0, 0), slots=[time(1, 30)]) == utc(2026, 3, 29, 1, 30)
    # 01:30 happens twice on 25 October: the first one (summer time, 00:30 UTC).
    assert slot(utc(2026, 10, 24, 23, 0), slots=[time(1, 30)]) == utc(2026, 10, 25, 0, 30)


def test_next_slot_needs_slots_and_a_positive_cap():
    with pytest.raises(ValueError):
        slot(utc(2026, 12, 1), slots=[])
    with pytest.raises(ValueError):
        slot(utc(2026, 12, 1), cap=0)


# --- schema v10 ---------------------------------------------------------------------------

def _queue_shape(conn) -> tuple:
    columns = [tuple(r)[1:] for r in conn.execute("PRAGMA table_info(posting_queue)")]
    indexes = sorted((r[1], r[2]) for r in conn.execute("PRAGMA index_list(posting_queue)"))
    return columns, indexes


@pytest.mark.parametrize("fixture, version", [("schema_v5.sql", 5), ("schema_v7.sql", 7)])
def test_upgrade_from_real_old_schemas_adds_the_posting_queue(ctx, fixture, version):
    import sqlite3
    from pathlib import Path
    ctx.db_path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(ctx.db_path)
    old.executescript((Path(__file__).parent / "fixtures" / fixture).read_text("utf-8"))
    old.execute(f"PRAGMA user_version = {version}")
    old.commit()
    old.close()

    conn = pipeline.open_db(ctx)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 14
    fresh = db.connect(ctx.root / "fresh.db")
    db.init(fresh)
    assert _queue_shape(conn) == _queue_shape(fresh)
    assert ("ix_posting_due", 0) in _queue_shape(conn)[1]
    columns = [c[0] for c in _queue_shape(conn)[0]]
    assert "checked_at" in columns
    # v11 (D36): the Instagram publisher's progress per row; v12 (D38): the Telegram message.
    assert columns[-9:] == ["container_id", "media_id", "story_status", "story_container_id",
                            "story_media_id", "story_attempts", "story_note", "caption",
                            "message_id"]
    for c in (conn, fresh):
        c.execute("PRAGMA foreign_keys = OFF")          # only the channel CHECK can refuse it
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("INSERT INTO posting_queue (deal_id, channel, due_at, created_at) "
                      "VALUES (1, 'whatsapp', 'x', 'x')")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("INSERT INTO posting_queue (deal_id, channel, due_at, created_at, "
                      "story_status) VALUES (1, 'instagram', 'x', 'x', 'maybe')")


def test_upgrade_from_v10_keeps_queued_posts_and_adds_the_progress_columns(ctx):
    """The real database is v10 (D32): its queued rows survive the ALTERs with empty progress."""
    import sqlite3
    from pathlib import Path
    ctx.db_path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(ctx.db_path)
    old.executescript((Path(__file__).parent / "fixtures" / "schema_v7.sql").read_text("utf-8"))
    old.execute("PRAGMA user_version = 7")
    old.commit()
    old.close()
    conn = db.connect(ctx.db_path)
    for version in (8, 9, 10):                          # what a v10 database went through
        for step in db.MIGRATIONS[version]:
            conn.execute(step)
    conn.execute("PRAGMA user_version = 10")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO posting_queue (deal_id, channel, due_at, created_at, attempts) "
                 "VALUES (1, 'instagram', '2026-12-01T09:00:00+00:00', "
                 "'2026-12-01T07:00:00+00:00', 2)")
    conn.commit()
    db.init(conn)
    [post] = db.posts(conn)
    assert (post.status, post.attempts, post.media_id, post.story_status, post.story_attempts) \
        == ("queued", 2, None, None, 0)


def test_upgrade_from_v11_keeps_posts_and_adds_the_telegram_message_id(ctx):
    """The real database is v11 (D36): its rows survive migration 12 with no message id."""
    import sqlite3
    from pathlib import Path
    ctx.db_path.parent.mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(ctx.db_path)
    old.executescript((Path(__file__).parent / "fixtures" / "schema_v7.sql").read_text("utf-8"))
    old.execute("PRAGMA user_version = 7")
    old.commit()
    old.close()
    conn = db.connect(ctx.db_path)
    for version in (8, 9, 10, 11):                      # what a v11 database went through
        for step in db.MIGRATIONS[version]:
            conn.execute(step)
    conn.execute("PRAGMA user_version = 11")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO posting_queue (deal_id, channel, due_at, created_at, status, "
                 "publisher, media_id) VALUES (1, 'instagram', '2026-12-01T09:00:00+00:00', "
                 "'2026-12-01T07:00:00+00:00', 'published', 'instagram', '1789')")
    conn.commit()
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    [post] = db.posts(conn)
    assert (post.status, post.media_id, post.message_id) == ("published", "1789", None)


def test_the_channel_check_in_sql_is_posting_channels():
    """One list of channels (posting.CHANNELS): the SQL CHECK of the fresh schema and of the
    migration, the config's publishers and the queue planner all follow it."""
    import re
    from pathlib import Path
    from escapadinha.config import PostingConfig
    schema = (Path(db.__file__).parent / "schema.sql").read_text("utf-8")
    for sql in (schema, db.POSTING_QUEUE_TABLE):
        table = sql[sql.index("CREATE TABLE IF NOT EXISTS posting_queue"):]
        listed = re.search(r"channel IN \(([^)]*)\)", table).group(1)
        assert tuple(re.findall(r"'([a-z]+)'", listed)) == posting.CHANNELS
    for sql in (schema, " ".join(db.MIGRATIONS[11])):         # story statuses: one list too
        table = sql[sql.index("posting_queue"):]
        listed = re.search(r"story_status IN \(([^)]*)\)", table).group(1)
        assert set(re.findall(r"'([a-z]+)'", listed)) == set(posting.StoryStatus)
    assert tuple(PostingConfig().publishers) == posting.CHANNELS
    assert PostingConfig(publishers={"telegram": "dry-run"}).publishers == {
        channel: "dry-run" for channel in posting.CHANNELS}
    with pytest.raises(ValueError, match="unknown channel"):
        PostingConfig(publishers={"whatsapp": "dry-run"})


# --- the queue through the pipeline seam ----------------------------------------------------

PENDING = "review/events/pending/"
# Tuesday 1 December 2026, 06:30 UTC = 06:30 Lisbon (winter time): before the first slot.
CHECKED = utc(2026, 12, 1, 6, 30)
APPLIED = utc(2026, 12, 1, 7, 0)


def approve_event(store, deal_id: int, checked: datetime = CHECKED, type: str = "approve",
                  created: datetime | None = None, **extra) -> str:
    """A decision as the review Function writes it (an approval's live check passed at
    `checked`; the decision itself at `created`, by default the same moment)."""
    event_id = str(uuid.uuid4())
    created = created or checked
    body = {"version": 1, "id": event_id, "type": type, "deal_id": deal_id,
            "created_at": db.utc_iso(created), "actor": "miguel@example.com", "note": None,
            "post_url": None,
            "live_check": {"valid": True, "price_eur": 58, "reason": "continua a 58 €",
                           "checked_at": db.utc_iso(checked)} if type == "approve" else None,
            **extra}
    store.put(f"{PENDING}{created:%Y%m%dT%H%M%SZ}-{event_id}.json", json.dumps(body).encode())
    return event_id


def second_deal(ctx, conn) -> int:
    """Another rendered LIS-LON promotion on a different stored offer of the same run."""
    used = db.deal_observation_ids(conn)
    obs = next(o for o in db.observations_seen_since(conn, db.latest_completed_run_id(conn))
               if o.id not in used and o.route_key == "LIS-LON")
    deal_id = db.insert_deal(conn, observation_id=obs.id, rule="median", baseline_median=100,
                             sample_size=25, discount_pct=0.4, threshold=0.3)
    db.set_deal_affiliate(conn, deal_id, f"https://aviasales.tpo.lu/deal-{deal_id}", None)
    db.set_deal_status(conn, deal_id, "rendered")
    return deal_id


def queue(conn) -> list[tuple]:
    return [(p.deal_id, p.channel, p.due_at, p.status) for p in db.posts(conn)]


@respx.mock
def test_an_applied_approval_queues_instagram_at_the_next_slot_and_telegram_at_once(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    event_id = approve_event(ctx.object_store, deal_id)
    [outcome] = pipeline.apply_review_events(ctx, conn, now=APPLIED)
    assert outcome.applied
    assert queue(conn) == [(deal_id, "telegram", APPLIED, "queued"),
                           (deal_id, "instagram", utc(2026, 12, 1, 9), "queued")]
    assert {p.event_id for p in db.posts(conn)} == {event_id}


@respx.mock
def test_approvals_in_one_run_take_consecutive_slots(ctx):
    conn = pipeline.open_db(ctx)
    first = rendered_deal(ctx, conn)
    second = second_deal(ctx, conn)
    approve_event(ctx.object_store, first)
    approve_event(ctx.object_store, second, checked=CHECKED.replace(second=1))
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    instagram = [(p.deal_id, p.due_at) for p in db.posts(conn) if p.channel == "instagram"]
    assert instagram == [(first, utc(2026, 12, 1, 9)), (second, utc(2026, 12, 1, 13))]


@respx.mock
def test_the_slots_and_cap_come_from_config(ctx):
    ctx.config.posting.instagram_slots = ["10:30"]
    ctx.config.posting.max_per_day = 1
    conn = pipeline.open_db(ctx)
    first = rendered_deal(ctx, conn)
    second = second_deal(ctx, conn)
    approve_event(ctx.object_store, first)
    approve_event(ctx.object_store, second, checked=CHECKED.replace(second=1))
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    instagram = [p.due_at for p in db.posts(conn) if p.channel == "instagram"]
    assert instagram == [utc(2026, 12, 1, 10, 30), utc(2026, 12, 2, 10, 30)]


@respx.mock
def test_refused_or_repeated_approvals_queue_nothing_more(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    approve_event(ctx.object_store, deal_id, live_check=None)       # refused: no price check
    [refused] = pipeline.apply_review_events(ctx, conn, now=APPLIED)
    assert not refused.applied and queue(conn) == []
    approve_event(ctx.object_store, deal_id)
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    approve_event(ctx.object_store, deal_id, checked=CHECKED.replace(second=5))   # again: refused
    [again] = pipeline.apply_review_events(ctx, conn, now=APPLIED)
    assert not again.applied and len(queue(conn)) == 2


# --- CLI ------------------------------------------------------------------------------------

def cli(ctx, monkeypatch, *args) -> str:
    from typer.testing import CliRunner
    from escapadinha import cli as cli_module
    monkeypatch.setenv("ESCAPADINHA_HOME", str(ctx.root))
    result = CliRunner().invoke(cli_module.app, list(args))
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


@respx.mock
def test_queue_list_shows_upcoming_posts_in_pt_pt(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    assert "Nenhuma publicação agendada." in cli(ctx, monkeypatch, "queue", "list")
    deal_id = approved(ctx, conn)
    out = cli(ctx, monkeypatch, "queue", "list")
    assert "2 publicações agendadas" in out
    assert f"Telegram deal {deal_id} Lisboa → Londres 58 € 01/12/2026 às 07:00" in out
    assert f"Instagram deal {deal_id} Lisboa → Londres 58 € 01/12/2026 às 09:00" in out

    publish(ctx, conn, APPLIED)
    out = cli(ctx, monkeypatch, "queue", "list")
    assert "1 publicação agendada" in out and "Telegram" not in out
    out = cli(ctx, monkeypatch, "queue", "list", "--all")
    assert "Telegram" in out and "publicada (dry-run)" in out


@respx.mock
def test_queue_list_shows_why_a_post_waits_or_was_cancelled(ctx, monkeypatch):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    publish(ctx, conn, utc(2026, 12, 1, 12, 31))          # not re-verified: both wait
    assert "Preço verificado há mais de 6 h" in cli(ctx, monkeypatch, "queue", "list")
    db.record_recheck(conn, deal_id, valid=False, latest_price=80,
                      reason="o preço subiu para 80 €", at=utc(2026, 12, 1, 13))
    publish(ctx, conn, utc(2026, 12, 1, 13))
    out = cli(ctx, monkeypatch, "queue", "list", "--all")
    assert "cancelada: A promoção expirou: o preço subiu para 80 €." in out


@respx.mock
def test_run_publishes_due_posts_after_the_recheck_before_the_path_decision(ctx, monkeypatch, npm):
    """Posting never waits for a full path: the step runs on every run, fast or full."""
    from test_pipeline import mock_api
    from test_web_build import web_package
    from test_website import real_slides
    web_package(ctx.root)                          # the full path builds the site (npm faked)
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    real_slides(conn, deal_id)                     # the approval sends the run down the full path
    db.set_meta(conn, pipeline.DISCOVERED_AT, db.utcnow().isoformat())   # no discovery this run
    approve_event(ctx.object_store, deal_id, checked=db.utcnow())
    mock_api()
    mock_links()
    out = cli(ctx, monkeypatch, "run", "--no-render")
    assert out.index("Run #") < out.index("[dry-run] Telegram") < out.index("Path:")
    assert out.index("Detection for run") < out.index("[dry-run] Telegram")   # after detect
    assert f"publicação Telegram deal {deal_id}: publicada (dry-run)" in out
    telegram = by_channel(conn)["telegram"]
    assert (telegram.status, telegram.publisher) == ("published", "dry-run")


@respx.mock
def test_the_local_review_page_offers_the_whatsapp_text_to_copy(ctx):
    from fastapi.testclient import TestClient
    from escapadinha.web import create_app
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    client = TestClient(create_app(ctx))
    [d] = client.get("/api/deals", params={"tab": "approved"}).json()["deals"]
    assert d["id"] == deal_id and DISCLOSURE in d["whatsapp_text"]
    assert f"👉 {db.get_deal(conn, deal_id)[0].affiliate_url}" in d["whatsapp_text"]
    page = client.get("/").text
    assert "copy-whatsapp" in page and "Copiar texto do WhatsApp" in page


# --- the publish step -----------------------------------------------------------------------

def approved(ctx, conn) -> int:
    """A rendered LIS-LON promotion approved by an event applied at APPLIED (07:00 UTC)."""
    deal_id = rendered_deal(ctx, conn)
    approve_event(ctx.object_store, deal_id)
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    return deal_id


def publish(ctx, conn, now, **kw) -> tuple[list[tuple], list[str]]:
    lines: list[str] = []
    results = pipeline.run_publish(ctx, conn, now=now, log=lines.append, **kw)
    return [(r.post.deal_id, r.post.channel, r.action) for r in results], lines


def by_channel(conn) -> dict[str, object]:
    return {p.channel: p for p in db.posts(conn)}


@respx.mock          # any HTTP request would fail: the dry-run publisher makes none
def test_the_dry_run_publisher_logs_due_posts_and_marks_them_published(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    link = db.get_deal(conn, deal_id)[0].affiliate_url

    done, lines = publish(ctx, conn, APPLIED)
    assert done == [(deal_id, "telegram", "published")]       # Instagram waits for 09:00
    log = "\n".join(lines)
    assert "[dry-run] Telegram" in log and f"deal {deal_id}" in log
    assert f"👉 {link}" in log and DISCLOSURE in log
    posts = by_channel(conn)
    assert (posts["telegram"].status, posts["telegram"].publisher) == ("published", "dry-run")
    assert posts["telegram"].result_url is None and posts["telegram"].settled_at == APPLIED
    assert posts["instagram"].status == "queued"

    assert publish(ctx, conn, utc(2026, 12, 1, 8, 59))[0] == []
    done, lines = publish(ctx, conn, utc(2026, 12, 1, 9, 0))
    assert done == [(deal_id, "instagram", "published")]
    log = "\n".join(lines)
    assert "[dry-run] Instagram" in log and "01/12/2026 às 09:00" in log
    assert "Lisboa → Londres desde 58 € ida e volta!" in log      # the Instagram caption
    assert publish(ctx, conn, utc(2026, 12, 2, 9, 0))[0] == []   # nothing twice
    assert db.get_deal(conn, deal_id)[0].status == "approved"    # a dry run publishes nothing


@respx.mock
def test_an_expired_promotion_cancels_its_posts_before_their_slot(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    db.record_recheck(conn, deal_id, valid=False, latest_price=80,
                      reason="o preço subiu para 80 €", at=APPLIED)
    done, lines = publish(ctx, conn, APPLIED)
    assert sorted(done) == [(deal_id, "instagram", "cancelled"), (deal_id, "telegram", "cancelled")]
    assert not any("[dry-run]" in line for line in lines)
    for post in db.posts(conn):
        assert post.status == "cancelled"
        assert post.reason == "A promoção expirou: o preço subiu para 80 €."


@respx.mock
def test_a_rejected_promotion_cancels_its_posts(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    approve_event(ctx.object_store, deal_id, checked=CHECKED.replace(minute=40), type="reject")
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    publish(ctx, conn, APPLIED)
    assert {p.reason for p in db.posts(conn)} == {"A promoção foi rejeitada."}


@respx.mock
def test_a_promotion_marked_published_by_hand_keeps_telegram_but_not_the_instagram_slot(ctx):
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    approve_event(ctx.object_store, deal_id, checked=CHECKED.replace(minute=40), type="published",
                  post_url="https://www.instagram.com/p/x/")
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    done, _ = publish(ctx, conn, APPLIED)
    assert sorted(done) == [(deal_id, "instagram", "cancelled"), (deal_id, "telegram", "published")]
    assert by_channel(conn)["instagram"].reason == \
        "A promoção já foi marcada como publicada no Instagram."


def mark_published(ctx, conn, deal_id, at):
    approve_event(ctx.object_store, deal_id, checked=at, type="published",
                  post_url="https://www.instagram.com/p/x/")
    pipeline.apply_review_events(ctx, conn, now=at)


@respx.mock
def test_a_published_promotions_queued_post_is_cancelled_once_its_check_is_too_old(ctx):
    """Published promotions are not rechecked any more (only db.OPEN_STATUSES are), so a queued
    Telegram post that missed its 6 h (e.g. the runs failed meanwhile) would wait forever: it
    is cancelled with the reason instead (D32)."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)                    # live check 06:30, applied 07:00
    mark_published(ctx, conn, deal_id, utc(2026, 12, 1, 7, 10))
    done, lines = publish(ctx, conn, utc(2026, 12, 1, 12, 31))
    assert sorted(done) == [(deal_id, "instagram", "cancelled"), (deal_id, "telegram", "cancelled")]
    assert not any("[dry-run]" in line for line in lines)
    assert by_channel(conn)["telegram"].reason == (
        "A promoção foi marcada como publicada e já não é verificada: o preço confirmado tem "
        "mais de 6 h.")
    assert publish(ctx, conn, utc(2026, 12, 2, 9))[0] == []            # nothing left waiting


@respx.mock
def test_a_published_promotions_post_still_goes_out_within_the_window(ctx):
    """Within 6 h of the last verification (here a recheck made while it was approved, later
    than the live check) the queued Telegram post of a published promotion goes out."""
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua",
                      at=utc(2026, 12, 1, 10))
    mark_published(ctx, conn, deal_id, utc(2026, 12, 1, 10, 30))
    done, _ = publish(ctx, conn, utc(2026, 12, 1, 15, 59))           # 5 h 59 after the recheck
    assert sorted(done) == [(deal_id, "instagram", "cancelled"), (deal_id, "telegram", "published")]


@respx.mock
def test_a_due_post_waits_until_a_recent_recheck_verified_the_price(ctx):
    conn = pipeline.open_db(ctx)                      # approved at 06:30, max_check_age 6 h
    deal_id = approved(ctx, conn)
    late = utc(2026, 12, 1, 12, 31)
    done, _ = publish(ctx, conn, late)
    assert sorted(done) == [(deal_id, "instagram", "waiting"), (deal_id, "telegram", "waiting")]
    posts = by_channel(conn)
    assert posts["telegram"].status == "queued" and posts["telegram"].attempts == 0
    assert posts["telegram"].last_error == \
        "Preço verificado há mais de 6 h: espera por uma recolha que o confirme."
    db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua", at=late)
    done, _ = publish(ctx, conn, late)
    assert sorted(done) == [(deal_id, "instagram", "published"), (deal_id, "telegram", "published")]


@respx.mock
def test_the_fallback_verification_is_the_approvals_live_check_not_the_approval(ctx):
    """The live check can be older than the approval (checked 06:30, approved at 07:00 on the
    page): the 6 h count from the check, which each queued post keeps (`checked_at`)."""
    conn = pipeline.open_db(ctx)
    deal_id = rendered_deal(ctx, conn)
    approve_event(ctx.object_store, deal_id, checked=CHECKED, created=utc(2026, 12, 1, 7, 0))
    pipeline.apply_review_events(ctx, conn, now=utc(2026, 12, 1, 7, 5))
    assert {p.checked_at for p in db.posts(conn)} == {CHECKED}
    assert db.get_deal(conn, deal_id)[0].reviewed_at == utc(2026, 12, 1, 7, 0)
    done, _ = publish(ctx, conn, utc(2026, 12, 1, 12, 45))      # 6 h 15 after the check
    assert sorted(done) == [(deal_id, "instagram", "waiting"), (deal_id, "telegram", "waiting")]
    done, _ = publish(ctx, conn, utc(2026, 12, 1, 12, 30))      # exactly 6 h: still good
    assert sorted(done) == [(deal_id, "instagram", "published"), (deal_id, "telegram", "published")]


def test_verdict_actions_are_an_enum():
    assert set(posting.VerdictAction) == {"publish", "later", "wait", "cancel"}
    assert set(posting.PostAction) == {"published", "cancelled", "waiting", "failed"}


class Failing:
    name = "falha"

    def publish(self, message):
        raise RuntimeError("API em baixo")


@respx.mock
def test_publisher_errors_are_retried_then_cancel_the_post(ctx):
    ctx.config.posting.max_attempts = 2
    conn = pipeline.open_db(ctx)
    deal_id = approved(ctx, conn)
    publishers = {"telegram": Failing(), "instagram": Failing()}
    done, _ = publish(ctx, conn, APPLIED, publishers=publishers)
    assert done == [(deal_id, "telegram", "failed")]
    post = by_channel(conn)["telegram"]
    assert (post.status, post.attempts, post.last_error) == \
        ("queued", 1, "RuntimeError: API em baixo")
    done, _ = publish(ctx, conn, APPLIED, publishers=publishers)
    assert done == [(deal_id, "telegram", "cancelled")]
    assert by_channel(conn)["telegram"].reason == \
        "O publicador falhou 2 vezes: RuntimeError: API em baixo"


@respx.mock
def test_a_backlog_of_instagram_posts_goes_out_one_per_run(ctx):
    conn = pipeline.open_db(ctx)
    first = rendered_deal(ctx, conn)
    second = second_deal(ctx, conn)
    approve_event(ctx.object_store, first)
    approve_event(ctx.object_store, second, checked=CHECKED.replace(second=1))
    pipeline.apply_review_events(ctx, conn, now=APPLIED)
    publish(ctx, conn, APPLIED)                                    # both Telegram posts
    for deal_id in (first, second):                                # rechecked by the 13:00 run
        db.record_recheck(conn, deal_id, valid=True, latest_price=58, reason="continua",
                          at=utc(2026, 12, 1, 13))
    done, _ = publish(ctx, conn, utc(2026, 12, 1, 13, 30))         # 09:00 and 13:00 both due
    assert done == [(first, "instagram", "published")]
    done, _ = publish(ctx, conn, utc(2026, 12, 1, 15, 30))
    assert done == [(second, "instagram", "published")]

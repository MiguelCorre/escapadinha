"""Database sync through the object store: pull/push, run session, lock, daily backups."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from escapadinha import cli
from escapadinha.config import Context
from escapadinha.storage import db, sync
from escapadinha.storage.objects import LocalObjectStore, LockHeld
from escapadinha.storage.s3 import S3ObjectStore

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


class Pc:
    """One machine: its own data/ folder, sharing the bucket with the others."""

    def __init__(self, root: Path):
        self.db_path = root / "data" / "escapadinha.db"
        self.state = root / "data" / "escapadinha.db.sync.json"

    def add_run(self) -> int:
        conn = db.connect(self.db_path)
        db.init(conn)
        run_id = db.start_run(conn, "travelpayouts")
        conn.close()
        return run_id

    def runs(self) -> int:
        conn = db.connect(self.db_path)
        try:
            return conn.execute("SELECT count(*) FROM fetch_runs").fetchone()[0]
        finally:
            conn.close()

    def pull(self, store, **kw):
        return sync.pull(store, self.db_path, self.state, log=lambda _: None, **kw)

    def push(self, store, **kw):
        return sync.push(store, self.db_path, self.state, owner="test", log=lambda _: None, **kw)

    def session(self, store, now=NOW, owner="run-a", log=lambda _: None):
        return sync.run_session(store, self.db_path, self.state, owner=owner, now=now, log=log)


@pytest.fixture(params=["local", "s3"])
def bucket(request, tmp_path):
    if request.param == "local":
        return LocalObjectStore(tmp_path / "bucket")
    return request.getfixturevalue("s3_store")


@pytest.fixture
def pcs(tmp_path):
    return Pc(tmp_path / "miguel"), Pc(tmp_path / "actions")


def test_push_then_pull_on_another_machine(bucket, pcs):
    miguel, actions = pcs
    run_id = miguel.add_run()
    meta = miguel.push(bucket)
    assert (meta.generation, meta.last_run_id) == (1, run_id)
    assert bucket.list("db/") == [sync.DB_KEY, sync.META_KEY]
    actions.pull(bucket)
    assert actions.runs() == 1
    assert sync.read_state(actions.state).generation == 1


def test_push_with_no_changes_uploads_nothing(bucket, pcs):
    miguel, _ = pcs
    miguel.add_run()
    miguel.push(bucket)
    assert miguel.push(bucket).generation == 1


def test_push_refuses_to_overwrite_a_newer_bucket_database(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    actions.pull(bucket)
    actions.add_run()
    actions.push(bucket)                                   # generation 2
    miguel.add_run()
    with pytest.raises(sync.SyncError, match="newer database: generation 2"):
        miguel.push(bucket)
    assert miguel.push(bucket, force=True).generation == 3


def test_push_refuses_a_never_synced_copy_when_the_bucket_has_one(bucket, pcs):
    miguel, actions = pcs
    actions.add_run()
    actions.push(bucket)
    miguel.add_run()
    with pytest.raises(sync.SyncError, match="never synced"):
        miguel.push(bucket)


def test_pull_refuses_to_drop_local_changes_unless_forced(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    actions.pull(bucket)
    actions.add_run()
    actions.push(bucket)
    miguel.add_run()                                       # local work not pushed
    with pytest.raises(sync.SyncError, match="changed since its last pull"):
        miguel.pull(bucket)
    miguel.pull(bucket, force=True, now=NOW)
    kept = list(miguel.db_path.parent.glob("escapadinha.db.local-*"))
    assert len(kept) == 1 and miguel.runs() == 2


def test_pull_with_an_empty_bucket_is_an_error(bucket, pcs):
    with pytest.raises(sync.SyncError, match="No database in the bucket"):
        pcs[0].pull(bucket)


def test_pull_refuses_bytes_that_are_not_a_database(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    bucket.put(sync.DB_KEY, b"not a database" * 100)
    with pytest.raises(sync.SyncError, match="integrity"):
        actions.pull(bucket)
    assert not actions.db_path.exists()


# --- run session ------------------------------------------------------------------

def test_run_session_pulls_works_pushes_and_unlocks(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    with actions.session(bucket):
        assert bucket.list("locks/") == ["locks/run"]
        actions.add_run()
    assert bucket.list("locks/") == []
    meta = sync.remote_meta(bucket)
    assert (meta.generation, meta.pushed_by, meta.last_run_id) == (2, "run-a", 2)


def test_held_lock_stops_the_run_before_it_touches_anything(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    with bucket.lock(sync.LOCK, owner="other", ttl=sync.LOCK_TTL, now=NOW):
        with pytest.raises(LockHeld, match="held by other"):
            with actions.session(bucket):
                pytest.fail("the run must not start")
    assert not actions.db_path.exists() and not actions.state.exists()
    assert sync.remote_meta(bucket).generation == 1


def test_run_session_pushes_what_a_failed_run_collected(bucket, pcs):
    _, actions = pcs
    with pytest.raises(RuntimeError):
        with actions.session(bucket):
            actions.add_run()
            raise RuntimeError("render failed")
    assert sync.remote_meta(bucket).generation == 1
    assert bucket.list("locks/") == []


def test_first_run_seeds_an_empty_bucket(bucket, pcs):
    miguel, _ = pcs
    messages = []
    with miguel.session(bucket, log=messages.append):
        miguel.add_run()
    assert "No database in the bucket yet" in messages[0]
    assert sync.remote_meta(bucket).generation == 1


def test_daily_backup_once_per_lisbon_day(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    for now in (NOW, NOW + timedelta(hours=2),
                datetime(2026, 10, 13, 23, 30, tzinfo=timezone.utc)):   # 00:30 on the 14th in Lisbon
        with actions.session(bucket, now=now):
            actions.add_run()
    assert bucket.list("backups/") == ["backups/2026-10-13/escapadinha.db",
                                       "backups/2026-10-14/escapadinha.db"]
    restored = Pc(actions.db_path.parent.parent.parent / "restore")
    restored.db_path.parent.mkdir(parents=True)
    restored.db_path.write_bytes(bucket.get("backups/2026-10-13/escapadinha.db"))
    assert restored.runs() == 1                            # the database before that day's first run


def test_restore_a_backup_and_push_it_live(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    with actions.session(bucket):                          # backs up generation 1 first
        actions.add_run()
    sync.restore(bucket, miguel.db_path, miguel.state, "2026-10-13", now=NOW, log=lambda _: None)
    assert miguel.runs() == 1
    assert miguel.push(bucket).generation == 3
    actions.pull(bucket)
    assert actions.runs() == 1
    with pytest.raises(KeyError):
        sync.restore(bucket, miguel.db_path, miguel.state, "2020-01-01", log=lambda _: None)


def test_local_changes_on_the_current_generation_are_kept_and_pushed(bucket, pcs):
    miguel, _ = pcs
    miguel.add_run()
    miguel.push(bucket)
    miguel.add_run()                                       # e.g. an approval on the PC, not pushed
    with miguel.session(bucket):
        miguel.add_run()
    assert miguel.runs() == 3
    assert sync.remote_meta(bucket).generation == 2


def test_local_changes_on_an_old_generation_are_set_aside(bucket, pcs):
    miguel, actions = pcs
    miguel.add_run()
    miguel.push(bucket)
    actions.pull(bucket)
    actions.add_run()
    actions.push(bucket)
    miguel.add_run()                                       # diverged from generation 1
    with miguel.session(bucket):
        pass
    assert miguel.runs() == 2                              # the bucket's two runs
    assert len(list(miguel.db_path.parent.glob("escapadinha.db.local-*"))) == 1


def test_upload_missing_archives_once(bucket, tmp_path):
    local = LocalObjectStore(tmp_path / "pc-objects")
    local.put("archive/runs/0000001.json.gz", b"1")
    local.put("archive/runs/0000002.json.gz", b"2")
    local.put("locks/run", b"{}")
    bucket.put("archive/runs/0000002.json.gz", b"2")
    assert sync.upload_missing(local, bucket) == ["archive/runs/0000001.json.gz"]
    assert sync.upload_missing(local, bucket) == []
    assert bucket.list("locks/") == []


def test_store_check_on_the_bucket(s3_store):
    assert all(ok for _, ok in sync.check(s3_store))
    assert s3_store.list() == []


# --- config + CLI ------------------------------------------------------------------

R2_KEYS = {"R2_ENDPOINT": "https://acc.r2.cloudflarestorage.com", "R2_ACCESS_KEY_ID": "k",
           "R2_SECRET_ACCESS_KEY": "s", "R2_BUCKET": "escapadinha"}


def test_object_store_is_r2_only_with_all_keys(tmp_path, monkeypatch):
    for name in R2_KEYS:
        monkeypatch.delenv(name, raising=False)
    assert isinstance(Context(root=tmp_path).object_store, LocalObjectStore)
    (tmp_path / ".env").write_text("R2_ENDPOINT=x\nR2_BUCKET=escapadinha\n", encoding="utf-8")
    assert isinstance(Context(root=tmp_path).object_store, LocalObjectStore)
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in R2_KEYS.items()),
                                   encoding="utf-8")
    ctx = Context(root=tmp_path)
    assert ctx.remote_store and isinstance(ctx.object_store, S3ObjectStore)
    assert ctx.object_store.bucket == "escapadinha"


@pytest.fixture
def remote_cli(tmp_path, monkeypatch):
    """CLI with R2 'configured', the bucket being a local directory."""
    bucket = LocalObjectStore(tmp_path / "bucket")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ESCAPADINHA_HOME", str(home))
    monkeypatch.setattr(Context, "remote_store", property(lambda self: True))
    monkeypatch.setattr(Context, "object_store", property(lambda self: bucket))
    return bucket, home


def test_run_with_a_held_lock_exits_cleanly(remote_cli):
    bucket, home = remote_cli
    with bucket.lock(sync.LOCK, owner="actions-1", ttl=sync.LOCK_TTL):
        result = CliRunner().invoke(cli.app, ["run"])
    assert result.exit_code == 0, result.output
    assert "Another run is in progress" in result.output and "actions-1" in result.output
    assert not (home / "data").exists()


def test_store_push_refuses_while_a_run_holds_the_lock(remote_cli):
    bucket, home = remote_cli
    Pc(home).add_run()
    with bucket.lock(sync.LOCK, owner="actions-1", ttl=sync.LOCK_TTL):
        result = CliRunner().invoke(cli.app, ["store", "push"])
    assert result.exit_code == 1
    assert "Not pushed" in result.output and bucket.list("db/") == []


def test_store_push_pull_status_commands(remote_cli):
    bucket, home = remote_cli
    Pc(home).add_run()
    runner = CliRunner()
    assert runner.invoke(cli.app, ["store", "push"]).exit_code == 0
    out = runner.invoke(cli.app, ["store", "status"]).output
    assert "generation 1" in out and "lock: free" in out and "unchanged" in out
    pulled = runner.invoke(cli.app, ["store", "pull"])
    assert pulled.exit_code == 0 and "Already up to date" in pulled.output


def test_store_commands_without_r2_keys(tmp_path, monkeypatch):
    for name in R2_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ESCAPADINHA_HOME", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["store", "status"]).exit_code == 0
    result = runner.invoke(cli.app, ["store", "push"])
    assert result.exit_code == 1 and "R2 keys not set" in result.output

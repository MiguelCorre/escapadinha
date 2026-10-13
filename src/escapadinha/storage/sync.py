"""The SQLite database kept in the object store between runs (D21).

Objects:
- `db/escapadinha.db`: a consistent copy (sqlite backup API, never the live file);
- `db/escapadinha.json`: its metadata, `generation` +1 on every push, sha256, who pushed, when,
  and the last collection run in it;
- `backups/<Lisbon date>/escapadinha.db`: the database as it was before the day's first run
  (deleted after 30 days by the bucket's lifecycle rule);
- `locks/run`: the run lock (see `ObjectStore.lock`).

Locally, `data/escapadinha.db.sync.json` remembers which generation the local file came from
and the file's sha256 at that moment. That is how a pull knows the local file has changes the
bucket lacks, and how a push knows the bucket moved on since the last pull.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from escapadinha.i18n_pt import LISBON, lisbon_timestamp
from escapadinha.storage import db
from escapadinha.storage.objects import ObjectStore

DB_KEY = "db/escapadinha.db"
META_KEY = "db/escapadinha.json"
BACKUP_PREFIX = "backups/"
LOCK = "run"
# Longer than any run (≈1–2 min at 10 routes, minutes at ~300). A crashed run's lock is taken
# over after this, so a scheduler's job timeout must stay below it.
LOCK_TTL = timedelta(minutes=60)

Log = Callable[[str], None]


class SyncError(RuntimeError):
    """A pull or push refused to overwrite changes (or found a broken copy)."""


@dataclass(frozen=True)
class RemoteDb:
    generation: int
    sha256: str
    size: int
    pushed_at: str
    pushed_by: str
    last_run_id: int | None = None

    def describe(self) -> str:
        run = f", last run #{self.last_run_id}" if self.last_run_id else ""
        when = lisbon_timestamp(datetime.fromisoformat(self.pushed_at))
        return f"generation {self.generation} ({when} by {self.pushed_by}{run})"


@dataclass(frozen=True)
class LocalState:
    generation: int     # remote generation the local file was pulled from or pushed as
    sha256: str         # the local file's hash right after that pull/push


def owner_id(command: str) -> str:
    """Unique lock owner: command, machine, process and a random suffix."""
    return f"{command}@{socket.gethostname()}#{os.getpid()}-{uuid.uuid4().hex[:6]}"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str | None:
    return _sha(path.read_bytes()) if path.is_file() else None


def _check(path: Path) -> None:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        result = str(exc)
    finally:
        conn.close()
    if result != "ok":
        raise SyncError(f"{path.name} failed the SQLite integrity check: {result}")


def snapshot(db_path: Path) -> bytes:
    """A consistent copy of a database that may be open elsewhere, checked before use."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "snapshot.db"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(copy)
        try:
            src.backup(dst)
        except sqlite3.DatabaseError as exc:
            raise SyncError(f"{db_path.name} cannot be copied: {exc}") from exc
        finally:
            dst.close()
            src.close()
        _check(copy)
        return copy.read_bytes()


def _last_run_id(data: bytes) -> int | None:
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        copy.write_bytes(data)
        conn = sqlite3.connect(copy)
        try:
            return conn.execute("SELECT max(id) FROM fetch_runs").fetchone()[0]
        except sqlite3.Error:
            return None
        finally:
            conn.close()


def remote_meta(store: ObjectStore) -> RemoteDb | None:
    try:
        return RemoteDb(**json.loads(store.get(META_KEY)))
    except KeyError:
        return None


def read_state(path: Path) -> LocalState | None:
    try:
        return LocalState(**json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None


def _write_state(path: Path, generation: int, db_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = LocalState(generation=generation, sha256=file_sha(db_path) or "")
    path.write_text(json.dumps(asdict(state)), encoding="utf-8")


def local_changed(db_path: Path, state: LocalState | None) -> bool:
    """The local file differs from what the last pull/push left (or was never synced)."""
    if not db_path.is_file():
        return False
    return state is None or file_sha(db_path) != state.sha256


def _keep_local_copy(db_path: Path, now: datetime) -> Path:
    keep = db_path.with_name(f"{db_path.name}.local-{now.astimezone(LISBON):%Y%m%dT%H%M%S}")
    try:
        keep.write_bytes(snapshot(db_path))
    except (SyncError, sqlite3.Error):                  # broken file: keep it as it is
        keep.write_bytes(db_path.read_bytes())
    return keep


def _download(store: ObjectStore, meta: RemoteDb, log: Log) -> tuple[bytes, RemoteDb]:
    data = store.get(DB_KEY)
    if _sha(data) != meta.sha256:                       # a push landed between the two reads?
        meta = remote_meta(store) or meta
        data = store.get(DB_KEY)
        if _sha(data) != meta.sha256:
            log(f"[yellow]![/] {DB_KEY} does not match its metadata (an interrupted push?); "
                "using the database object, which is the newer of the two.")
    return data, meta


def _install(db_path: Path, data: bytes) -> None:
    """Replace the local database file atomically, after an integrity check."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(f"{db_path.name}.download")
    tmp.write_bytes(data)
    try:
        _check(tmp)
    except SyncError:
        tmp.unlink(missing_ok=True)
        raise
    for suffix in ("-journal", "-wal", "-shm"):         # never pair a new file with an old journal
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    os.replace(tmp, db_path)


def _up_to_date(db_path: Path, state_path: Path, state: LocalState | None, meta: RemoteDb) -> bool:
    """The local file is the bucket's current generation: untouched since that pull/push, or
    byte-identical to it (then the state file is brought up to date)."""
    if not db_path.is_file():
        return False
    if state and state.generation == meta.generation and not local_changed(db_path, state):
        return True
    if file_sha(db_path) == meta.sha256:
        _write_state(state_path, meta.generation, db_path)
        return True
    return False


def pull(store: ObjectStore, db_path: Path, state_path: Path, *, force: bool = False,
         now: datetime | None = None, log: Log = print) -> RemoteDb:
    """Replace the local database with the bucket's. Refuses to drop local changes unless
    `force` (then a copy is kept next to it as `escapadinha.db.local-<time>`)."""
    meta = remote_meta(store)
    if meta is None:
        raise SyncError("No database in the bucket yet: `escapadinha store push` uploads this one.")
    state = read_state(state_path)
    if _up_to_date(db_path, state_path, state, meta):
        log(f"Already up to date: {meta.describe()}.")
        return meta
    if local_changed(db_path, state):
        base = f"generation {state.generation}" if state else "a copy never synced"
        if not force:
            raise SyncError(
                f"The local database changed since its last pull/push (based on {base}); "
                f"the bucket has {meta.describe()}. Push it first (`escapadinha store push`) "
                "or discard it with `escapadinha store pull --force` (a copy is kept).")
        log(f"[yellow]![/] Local changes kept as {_keep_local_copy(db_path, now or db.utcnow())}")
    data, meta = _download(store, meta, log)
    _install(db_path, data)
    _write_state(state_path, meta.generation, db_path)
    log(f"Pulled {meta.describe()}.")
    return meta


def push(store: ObjectStore, db_path: Path, state_path: Path, *, owner: str,
         force: bool = False, now: datetime | None = None, log: Log = print) -> RemoteDb:
    """Upload a consistent copy of the local database. The caller holds the run lock.

    Refuses when the bucket moved on since this copy was pulled (another run or PC pushed),
    unless `force`. Nothing is uploaded when neither side changed.
    """
    if not db_path.is_file():
        raise SyncError(f"No local database at {db_path}.")
    meta = remote_meta(store)
    state = read_state(state_path)
    if meta is not None:
        base = state.generation if state else None
        if not force and (base is None or meta.generation > base):
            have = f"generation {base}" if base is not None else "a copy never synced"
            raise SyncError(
                f"The bucket has a newer database: {meta.describe()}; this one is based on "
                f"{have}. Pull it first (`escapadinha store pull`) or overwrite it with "
                "`escapadinha store push --force`.")
        if not local_changed(db_path, state) and meta.generation == base:
            log(f"Nothing to push: unchanged since {meta.describe()}.")
            return meta
    data = snapshot(db_path)
    new = RemoteDb(generation=(meta.generation if meta else 0) + 1, sha256=_sha(data),
                   size=len(data), pushed_at=(now or db.utcnow()).isoformat(), pushed_by=owner,
                   last_run_id=_last_run_id(data))
    store.put(DB_KEY, data)                             # database first: metadata never points
    store.put(META_KEY, json.dumps(asdict(new)).encode())  # at bytes that are not there yet
    _write_state(state_path, new.generation, db_path)
    log(f"Pushed {new.describe()}, {new.size / 1e6:.2f} MB.")
    return new


def prepare_run(store: ObjectStore, db_path: Path, state_path: Path, *,
                now: datetime | None = None, log: Log = print) -> None:
    """Bring the local file up to the bucket's database before a run (lock held).

    Never blocks a run: local changes on top of the bucket's current generation are kept
    (fast-forward, pushed at the end); local changes on top of an older one are set aside
    as a `.local-<time>` copy and the bucket's database is used.
    """
    meta = remote_meta(store)
    if meta is None:
        what = "this PC's database" if db_path.is_file() else "a new database"
        log(f"No database in the bucket yet: {what} is uploaded at the end of the run.")
        return
    state = read_state(state_path)
    if _up_to_date(db_path, state_path, state, meta):
        log(f"Local database is {meta.describe()}.")
        return
    if local_changed(db_path, state) and state and state.generation == meta.generation:
        log(f"Using this PC's database: changed since {meta.describe()}, which is still current.")
        return
    pull(store, db_path, state_path, force=True, now=now, log=log)


def backup_if_first_today(store: ObjectStore, db_path: Path, *, now: datetime | None = None) -> str | None:
    """Store `backups/<Lisbon date>/escapadinha.db` unless today's exists. Returns the key."""
    if not db_path.is_file():
        return None
    day = (now or db.utcnow()).astimezone(LISBON).date().isoformat()
    if store.list(f"{BACKUP_PREFIX}{day}/"):
        return None
    key = f"{BACKUP_PREFIX}{day}/escapadinha.db"
    store.put(key, snapshot(db_path))
    return key


@contextmanager
def run_session(store: ObjectStore, db_path: Path, state_path: Path, *, owner: str,
                now: datetime | None = None, log: Log = print) -> Iterator[None]:
    """lock → pull → daily backup → (the run) → push → unlock.

    Raises `LockHeld` before touching anything when another run holds the lock. The database
    is pushed even when the run fails halfway: what it collected is already in it, and its
    archives are already in the bucket. A copy that fails the integrity check is not pushed.
    """
    with store.lock(LOCK, owner=owner, ttl=LOCK_TTL, now=now):
        prepare_run(store, db_path, state_path, now=now, log=log)
        key = backup_if_first_today(store, db_path, now=now)
        if key:
            log(f"Daily backup: {key}")
        try:
            yield
        finally:
            if db_path.is_file():
                push(store, db_path, state_path, owner=owner, now=now, log=log)


def restore(store: ObjectStore, db_path: Path, state_path: Path, day: str, *,
            now: datetime | None = None, log: Log = print) -> str:
    """Put the daily backup of `day` (YYYY-MM-DD) in place of the local database.

    The current local file is kept as `.local-<time>`. The local copy is then marked as a change
    on top of the bucket's current generation, so `store push` uploads it as the next one.
    """
    key = f"{BACKUP_PREFIX}{day}/escapadinha.db"
    data = store.get(key)                               # KeyError: no backup that day
    if db_path.is_file():
        log(f"Current local database kept as {_keep_local_copy(db_path, now or db.utcnow())}")
    _install(db_path, data)
    meta = remote_meta(store)
    state = LocalState(generation=meta.generation if meta else 0, sha256="restored")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(asdict(state)), encoding="utf-8")
    log(f"Restored {key} to {db_path}. Check it, then `escapadinha store push`.")
    return key


def upload_missing(local: ObjectStore, remote: ObjectStore, prefix: str = "archive/") -> list[str]:
    """Copy objects under `prefix` that the bucket lacks (one-off: the raw archives written to
    data/objects/ before R2 was configured, which the database's `archive_key`s point to)."""
    present = set(remote.list(prefix))
    missing = [k for k in local.list(prefix) if k not in present]
    for key in missing:
        remote.put(key, local.get(key))
    return missing


def check(store: ObjectStore) -> list[tuple[str, bool]]:
    """Round trip on the real bucket with throwaway keys: put/get/list/delete and the lock's
    conditional writes. Every step must be True before trusting the bucket with the run lock."""
    from escapadinha.storage.objects import LockHeld

    token = uuid.uuid4().hex[:12]
    key, lock = f"check/{token}", f"check-{token}"
    results = []
    store.put(key, b"escapadinha")
    results.append(("put + get", store.get(key) == b"escapadinha"))
    results.append(("list", store.list("check/").count(key) == 1))
    store.delete(key)
    results.append(("delete", key not in store.list("check/")))
    with store.lock(lock, owner="check-a", ttl=timedelta(minutes=5)):
        try:
            with store.lock(lock, owner="check-b", ttl=timedelta(minutes=5)):
                refused = False
        except LockHeld:
            refused = True
        results.append(("lock refuses a second owner (If-None-Match)", refused))
    results.append(("lock released", f"locks/{lock}" not in store.list("locks/")))
    past = db.utcnow() - timedelta(hours=1)
    stale = store.lock(lock, owner="check-a", ttl=timedelta(minutes=5), now=past)
    stale.__enter__()
    with store.lock(lock, owner="check-b", ttl=timedelta(minutes=5)):
        stale.__exit__(None, None, None)
        results.append(("expired lock taken over, kept from its old owner (If-Match)",
                        f"locks/{lock}" in store.list("locks/")))
    results.append(("lock released after takeover", f"locks/{lock}" not in store.list("locks/")))
    return results


def status(store: ObjectStore, db_path: Path, state_path: Path) -> dict:
    """What `escapadinha store status` prints."""
    lock = None
    try:
        lock = json.loads(store.get(f"locks/{LOCK}"))
    except KeyError:
        pass
    state = read_state(state_path)
    backups = sorted({k.split("/")[1] for k in store.list(BACKUP_PREFIX) if k.count("/") >= 2})
    return {"remote": remote_meta(store), "lock": lock, "state": state,
            "local_exists": db_path.is_file(), "local_changed": local_changed(db_path, state),
            "backups": backups}

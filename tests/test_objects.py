"""ObjectStore contract. Every implementation (local now, R2 with #4) must pass these."""

from datetime import datetime, timedelta, timezone

import pytest

from escapadinha.storage.objects import LocalObjectStore, LockHeld

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=30)


@pytest.fixture(params=["local"])
def store(request, tmp_path):
    if request.param == "local":
        return LocalObjectStore(tmp_path / "objects")
    raise NotImplementedError(request.param)


def test_put_get_overwrite(store):
    store.put("archive/runs/1.json.gz", b"one")
    assert store.get("archive/runs/1.json.gz") == b"one"
    store.put("archive/runs/1.json.gz", b"two")
    assert store.get("archive/runs/1.json.gz") == b"two"


def test_missing_object_is_a_key_error(store):
    with pytest.raises(KeyError):
        store.get("nope")


def test_list_by_prefix_sorted(store):
    for key in ("b/2", "a/1", "b/1", "c"):
        store.put(key, b"x")
    assert store.list() == ["a/1", "b/1", "b/2", "c"]
    assert store.list("b/") == ["b/1", "b/2"]
    assert store.list("zzz") == []


def test_delete_is_idempotent(store):
    store.put("a", b"x")
    store.delete("a")
    store.delete("a")
    assert store.list() == []


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "..", "a//b", "a b", "a/"])
def test_invalid_keys_are_rejected(store, key):
    with pytest.raises(ValueError):
        store.put(key, b"x")


def test_lock_is_exclusive_and_released(store):
    with store.lock("run", owner="a", ttl=TTL, now=NOW):
        with pytest.raises(LockHeld, match="held by a"):
            with store.lock("run", owner="b", ttl=TTL, now=NOW):
                pass
    with store.lock("run", owner="b", ttl=TTL, now=NOW):   # free again
        pass
    assert store.list("locks/") == []


def test_lock_released_on_error(store):
    with pytest.raises(RuntimeError):
        with store.lock("run", owner="a", ttl=TTL, now=NOW):
            raise RuntimeError("boom")
    assert store.list("locks/") == []


def test_expired_lock_is_taken_over_and_kept_from_the_old_owner(store):
    stale = store.lock("run", owner="a", ttl=TTL, now=NOW)
    stale.__enter__()                                       # a crashed run never released it
    later = NOW + TTL + timedelta(seconds=1)
    with store.lock("run", owner="b", ttl=TTL, now=later):
        stale.__exit__(None, None, None)                    # old owner wakes up: must not free b's lock
        with pytest.raises(LockHeld, match="held by b"):
            with store.lock("run", owner="c", ttl=TTL, now=later):
                pass

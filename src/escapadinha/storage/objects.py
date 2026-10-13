"""Object storage behind one small interface: get/put/list/delete/lock.

`LocalObjectStore` keeps objects as files under a directory (tests, Miguel's PC). An
S3-compatible implementation for Cloudflare R2 comes with #4 and must pass the same
contract tests (tests/test_objects.py).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from escapadinha.storage.db import utcnow

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class LockHeld(RuntimeError):
    """Another run holds the lock and it has not expired."""


class ObjectStore(Protocol):
    def get(self, key: str) -> bytes:
        """The object's bytes. Raises KeyError when it does not exist."""
        ...

    def put(self, key: str, data: bytes) -> None:
        """Create or replace an object (readers never see a partial object)."""
        ...

    def list(self, prefix: str = "") -> list[str]:
        """Keys starting with `prefix`, sorted."""
        ...

    def delete(self, key: str) -> None:
        """Remove an object; a missing key is not an error."""
        ...

    def lock(self, name: str, *, owner: str, ttl: timedelta,
             now: datetime | None = None) -> AbstractContextManager[None]:
        """Hold `locks/<name>` for the duration of a `with` block. Raises LockHeld when
        another owner holds an unexpired lock; an expired lock is taken over."""
        ...


def check_key(key: str) -> str:
    """Keys are relative slash-separated paths: no '..', no leading slash, no spaces."""
    if not _KEY.match(key) or ".." in key.split("/"):
        raise ValueError(f"Invalid object key: {key!r}")
    return key


class LocalObjectStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / check_key(key)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def list(self, prefix: str = "") -> list[str]:
        if not self.root.exists():
            return []
        keys = (p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
                if p.is_file() and not p.name.startswith("."))
        return sorted(k for k in keys if k.startswith(prefix))

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    @contextmanager
    def lock(self, name: str, *, owner: str, ttl: timedelta,
             now: datetime | None = None) -> Iterator[None]:
        key = f"locks/{name}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        now = now or utcnow()
        body = json.dumps({"owner": owner, "expires_at": (now + ttl).isoformat()}).encode()
        try:
            with open(path, "xb") as f:              # atomic create: only one winner
                f.write(body)
        except FileExistsError:
            held = json.loads(path.read_bytes() or b"{}")
            expires = held.get("expires_at")
            if expires and datetime.fromisoformat(expires) > now:
                raise LockHeld(f"lock {name} held by {held.get('owner')} until {expires}") from None
            self.put(key, body)                      # expired: take it over
        try:
            yield
        finally:
            current = json.loads(path.read_bytes()) if path.exists() else {}
            if current.get("owner") == owner:
                path.unlink(missing_ok=True)

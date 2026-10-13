"""`ObjectStore` on an S3-compatible bucket (Cloudflare R2), same contract as `LocalObjectStore`.

The lock is one JSON object `locks/<name>` ({owner, expires_at}) guarded by conditional writes,
which R2 and S3 both honour:
- acquire: PUT with `If-None-Match: *` (only one creator wins, the others get 412);
- take over an expired lock: PUT with `If-Match: <etag we read>` (two runs racing for the same
  stale lock: only one wins);
- release: only if the object still names us, DELETE with `If-Match: <etag>` (falls back to a
  plain DELETE where conditional deletes are not implemented).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from escapadinha.storage.db import utcnow
from escapadinha.storage.objects import LockHeld, check_key

# What a store call raises when the bucket (or the disk under `LocalObjectStore`) fails: for
# steps that report the failure and go on instead of failing the run.
STORE_ERRORS: tuple[type[Exception], ...] = (BotoCoreError, ClientError, OSError)

_CONFLICT = {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}
_MISSING = {"NoSuchKey", "404", "NotFound"}


def _code(exc: Exception) -> str:
    response = getattr(exc, "response", None) or {}
    return str(response.get("Error", {}).get("Code", ""))


def _status(exc: Exception) -> int:
    response = getattr(exc, "response", None) or {}
    return int(response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))


def _is(exc: Exception, codes: set[str], status: int) -> bool:
    return _code(exc) in codes or _status(exc) == status


def r2_client(endpoint: str, access_key_id: str, secret_access_key: str) -> Any:
    """boto3 S3 client for R2. Checksums only when required: what Cloudflare documents for
    boto3 ≥ 1.36, whose default CRC headers R2 did not always accept."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key, region_name="auto",
        config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"},
                      request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"))


class S3ObjectStore:
    def __init__(self, client: Any, bucket: str):
        self.client = client
        self.bucket = bucket

    def __repr__(self) -> str:
        return f"S3ObjectStore(bucket={self.bucket!r})"

    def get(self, key: str) -> bytes:
        return self._get(check_key(key))[0]

    def _get(self, key: str) -> tuple[bytes, str]:
        """(bytes, etag); KeyError when missing."""
        from botocore.exceptions import ClientError
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is(exc, _MISSING, 404):
                raise KeyError(key) from None
            raise
        return obj["Body"].read(), obj["ETag"]

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=check_key(key), Body=data)

    def list(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket,
                                                                       Prefix=prefix)
        for page in pages:
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=check_key(key))   # 204 even if missing

    def _conditional_put(self, key: str, body: bytes, **condition: str) -> bool:
        """True if written; False if the condition failed (someone else got there first)."""
        from botocore.exceptions import ClientError
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body,
                                   ContentType="application/json", **condition)
        except ClientError as exc:
            if _is(exc, _CONFLICT, 412) or _status(exc) == 409:
                return False
            raise
        return True

    @contextmanager
    def lock(self, name: str, *, owner: str, ttl: timedelta,
             now: datetime | None = None) -> Iterator[None]:
        key = check_key(f"locks/{name}")
        now = now or utcnow()
        body = json.dumps({"owner": owner, "expires_at": (now + ttl).isoformat()}).encode()
        self._acquire(key, name, body, now)
        try:
            yield
        finally:
            self._release(key, owner)

    def _acquire(self, key: str, name: str, body: bytes, now: datetime) -> None:
        for _ in range(3):                                  # the holder may release mid-way
            if self._conditional_put(key, body, IfNoneMatch="*"):
                return
            try:
                raw, etag = self._get(key)
            except KeyError:
                continue                                    # released in between: try again
            held = json.loads(raw or b"{}")
            expires = held.get("expires_at")
            if expires and datetime.fromisoformat(expires) > now:
                raise LockHeld(f"lock {name} held by {held.get('owner')} until {expires}")
            if self._conditional_put(key, body, IfMatch=etag):   # expired: take it over
                return
        raise LockHeld(f"lock {name} is being taken by another run")

    def _release(self, key: str, owner: str) -> None:
        from botocore.exceptions import ClientError
        try:
            raw, etag = self._get(key)
        except KeyError:
            return
        if json.loads(raw or b"{}").get("owner") != owner:
            return                                          # taken over after it expired
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key, IfMatch=etag)
        except ClientError as exc:
            if _is(exc, _CONFLICT, 412):
                return                                      # changed hands since we read it
            if _status(exc) in (400, 501) or _code(exc) == "NotImplemented":
                self.client.delete_object(Bucket=self.bucket, Key=key)
            else:
                raise

"""Schema upgrades are atomic per version: a step that fails leaves the database at the version
before it, with nothing of the failed version applied, so the next run can start it over."""

from __future__ import annotations

import sqlite3

import pytest

from escapadinha.storage import db


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_a_failed_migration_leaves_the_previous_version_intact(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "x.db")
    db.init(conn)
    before = db.SCHEMA_VERSION

    def explode(_conn: sqlite3.Connection) -> None:
        raise RuntimeError("half-way")

    monkeypatch.setattr(db, "SCHEMA_VERSION", before + 1)
    monkeypatch.setitem(db.MIGRATIONS, before + 1,
                        ["ALTER TABLE deals ADD COLUMN half_way TEXT", explode])
    with pytest.raises(RuntimeError, match="half-way"):
        db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before
    assert "half_way" not in _columns(conn, "deals")

    # The next run applies the whole version again, from the start.
    monkeypatch.setitem(db.MIGRATIONS, before + 1, ["ALTER TABLE deals ADD COLUMN half_way TEXT"])
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before + 1
    assert "half_way" in _columns(conn, "deals")


def test_each_version_commits_with_its_stamp(tmp_path, monkeypatch):
    """Two versions: the first lands even when the second fails, so a retry resumes after it."""
    conn = db.connect(tmp_path / "x.db")
    db.init(conn)
    before = db.SCHEMA_VERSION
    monkeypatch.setattr(db, "SCHEMA_VERSION", before + 2)
    monkeypatch.setitem(db.MIGRATIONS, before + 1, ["ALTER TABLE deals ADD COLUMN first TEXT"])
    monkeypatch.setitem(db.MIGRATIONS, before + 2, ["ALTER TABLE deals ADD COLUMN second TEXT",
                                                    "ALTER TABLE no_such_table ADD COLUMN x TEXT"])
    with pytest.raises(sqlite3.OperationalError):
        db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == before + 1
    assert "first" in _columns(conn, "deals") and "second" not in _columns(conn, "deals")

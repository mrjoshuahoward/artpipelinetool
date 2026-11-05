"""SQLite store under <root>/.artpipeline/. WAL mode + BEGIN IMMEDIATE transactions make it
safe for parallel subagents and a CLI running next to the MCP server."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from artpipeline import errors as E
from artpipeline.errors import PipelineError

STATE_DIR = ".artpipeline"
DB_NAME = "pipeline.db"
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    ord INTEGER NOT NULL,
    spec TEXT NOT NULL,            -- AssetSpec JSON (by alias)
    cls TEXT NOT NULL,             -- resolved AssetClass JSON
    status TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires TEXT,
    extra_attempts INTEGER NOT NULL DEFAULT 0,
    in_brief INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    asset_id TEXT NOT NULL REFERENCES assets(id),
    n INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    agent TEXT NOT NULL,
    provenance TEXT NOT NULL,
    change_from_previous TEXT,
    source_path TEXT,
    processed_path TEXT,
    renditions TEXT,
    checks TEXT,
    passed INTEGER,
    sheet_id INTEGER,
    decision TEXT,                 -- approved | rejected | failed_checks | superseded | NULL
    decision_by TEXT,
    reason TEXT,
    decided_at TEXT,
    style_lock_version INTEGER,
    PRIMARY KEY (asset_id, n)
);
CREATE TABLE IF NOT EXISTS style_locks (
    version INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    by TEXT NOT NULL,
    style_block TEXT NOT NULL,
    palette TEXT NOT NULL,
    hero_ids TEXT NOT NULL,
    refs TEXT NOT NULL,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS gates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,            -- batch | in_engine
    created_at TEXT NOT NULL,
    asset_ids TEXT NOT NULL,
    sheet_id INTEGER,
    passed_by TEXT,
    passed_at TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS sheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    path TEXT NOT NULL,
    items TEXT NOT NULL            -- [[asset_id, n], ...]
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    asset_id TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_asset ON events(asset_id);
"""


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state_dir = self.root / STATE_DIR
        self.db_path = self.state_dir / DB_NAME

    @classmethod
    def create(cls, root: Path) -> "Store":
        s = cls(root)
        s.state_dir.mkdir(parents=True, exist_ok=True)
        # Keep attempt files out of git without touching the user's own .gitignore.
        gi = s.state_dir / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n", encoding="utf-8")
        conn = sqlite3.connect(s.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        finally:
            conn.close()
        return s

    @classmethod
    def open(cls, root: Path) -> "Store":
        s = cls(root)
        if not s.db_path.is_file():
            raise PipelineError(
                E.NO_PIPELINE,
                f"No pipeline at {s.root}.",
                hint="Run 'init <brief>' first, or pass --root pointing at the folder that holds .artpipeline/.",
            )
        return s

    @classmethod
    def discover(cls, start: Path | None = None) -> "Store":
        """Find the pipeline: $ARTPIPELINE_ROOT, else walk up from `start` (default cwd)."""
        env = os.environ.get("ARTPIPELINE_ROOT")
        if env:
            return cls.open(Path(env))
        here = (start or Path.cwd()).resolve()
        for d in (here, *here.parents):
            if (d / STATE_DIR / DB_NAME).is_file():
                return cls(d)
        raise PipelineError(
            E.NO_PIPELINE,
            f"No .artpipeline/ found in {here} or any parent folder.",
            hint="Run 'init <brief>' first, or pass --root / set ARTPIPELINE_ROOT.",
        )

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def dumps(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def loads(v: str | None) -> Any:
    return None if v is None else json.loads(v)

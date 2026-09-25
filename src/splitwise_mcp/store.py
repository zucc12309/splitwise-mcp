"""Short atomic transactions; SQLite locally, PostgreSQL for remote durability."""

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import AppError

DDL = """
CREATE TABLE IF NOT EXISTS sw_schema (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS sw_operations (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, account BIGINT NOT NULL,
 operation_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 draft TEXT NOT NULL, draft_hash TEXT NOT NULL, expires BIGINT NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('pending_approval','approved','submitting','succeeded','failed','unknown_outcome')),
 approval_hash TEXT, lease_until BIGINT, expense_id BIGINT, error_code TEXT,
 UNIQUE(owner, operation_key)
);
INSERT INTO sw_schema(version) VALUES (1) ON CONFLICT DO NOTHING;
"""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Store:
    def __init__(self, database: str):
        self.database = database
        self.postgres = database.startswith("postgresql://")
        if not self.postgres:
            path = Path(database).expanduser()
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.database = str(path)
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(path, 0o600)

    @contextmanager
    def transaction(self):
        conn: Any
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(
                self.database,
                row_factory=dict_row,
                connect_timeout=5,
                options="-c statement_timeout=5000",
            )
        else:
            conn = sqlite3.connect(self.database, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def sql(self, conn, sql, args=()):
        return conn.execute(sql.replace("?", "%s") if self.postgres else sql, args)

    def migrate(self):
        with self.transaction() as conn:
            # PostgreSQL serializes concurrent first migrations with a transaction lock.
            if self.postgres:
                conn.execute("SELECT pg_advisory_xact_lock(731958221)")
            for statement in DDL.split(";"):
                if statement.strip():
                    self.sql(conn, statement)
            versions = {
                r["version"] for r in self.sql(conn, "SELECT version FROM sw_schema").fetchall()
            }
            if not versions <= {1, 2}:
                raise AppError(
                    "persistence_unavailable", "Database schema is newer than this application."
                )
            if 2 not in versions:
                self.sql(conn, "ALTER TABLE sw_operations ADD COLUMN approval_expires BIGINT")
                self.sql(conn, "INSERT INTO sw_schema(version) VALUES (2)")

    def check_schema(self):
        try:
            with self.transaction() as conn:
                versions = self.sql(conn, "SELECT version FROM sw_schema").fetchall()
                if {r["version"] for r in versions} != {1, 2}:
                    raise ValueError
        except Exception:
            raise AppError(
                "persistence_unavailable",
                "Run the explicit migration command on the configured database first.",
            ) from None

    def put(self, owner: str, account: int, key: str, request_hash: str, draft: dict) -> dict:
        draft_id = uuid.uuid4().hex
        expires = int(time.time()) + 900
        with self.transaction() as conn:
            self.sql(
                conn,
                """INSERT INTO sw_operations
                (id,owner,account,operation_key,request_hash,draft,draft_hash,expires,state)
                VALUES (?,?,?,?,?,?,?,?, 'pending_approval') ON CONFLICT(owner,operation_key) DO NOTHING""",
                (
                    draft_id,
                    owner,
                    account,
                    key,
                    request_hash,
                    canonical(draft),
                    digest(draft),
                    expires,
                ),
            )
            row = dict(
                self.sql(
                    conn,
                    "SELECT * FROM sw_operations WHERE owner=? AND operation_key=?",
                    (owner, key),
                ).fetchone()
            )
            if row["request_hash"] != request_hash or row["account"] != account:
                raise AppError(
                    "operation_conflict",
                    "Operation key already refers to another payload/account; use a new key for a new proposal.",
                )
            if row["draft"] == "{}":
                raise AppError(
                    "expired_draft",
                    "Draft details were pruned; this operation key cannot be reused.",
                )
            return self._verify(row)

    @staticmethod
    def _verify(row: dict) -> dict:
        parsed = json.loads(row["draft"])
        if digest(parsed) != row["draft_hash"]:
            raise AppError("draft_integrity", "Stored draft integrity check failed.")
        return {**row, "draft": parsed}

    def get(self, owner: str, account: int, draft_id: str) -> dict:
        with self.transaction() as conn:
            self.sql(
                conn,
                """UPDATE sw_operations SET state='unknown_outcome',error_code='interrupted_submission'
                WHERE id=? AND owner=? AND account=? AND state='submitting' AND lease_until < ?""",
                (draft_id, owner, account, int(time.time())),
            )
            row = self.sql(
                conn,
                "SELECT * FROM sw_operations WHERE id=? AND owner=? AND account=?",
                (draft_id, owner, account),
            ).fetchone()
            if row is None:
                raise AppError(
                    "unavailable", "Draft or operation unavailable to this owner/account."
                )
            return self._verify(dict(row))

    def approve(
        self, owner: str, account: int, draft_id: str, approval_hash: str, approval_expires: int
    ):
        """Persist verified evidence for a trusted external approval interface, without submitting."""
        with self.transaction() as conn:
            now = int(time.time())
            return (
                self.sql(
                    conn,
                    """UPDATE sw_operations SET state='approved',approval_hash=?,approval_expires=?
                WHERE id=? AND owner=? AND account=? AND state IN ('pending_approval','approved')
                AND expires>? AND ?>? AND ?<=expires""",
                    (
                        approval_hash,
                        approval_expires,
                        draft_id,
                        owner,
                        account,
                        now,
                        approval_expires,
                        now,
                        approval_expires,
                    ),
                ).rowcount
                == 1
            )

    def reserve(
        self, owner: str, account: int, draft_id: str, approval_hash: str, approval_expires: int
    ) -> bool:
        """Accept current verified evidence and reserve in ONE conditional transaction.

        A fresh approval can replace evidence only before submission. The same predicate
        enforces both expiry deadlines, so concurrent callers cannot claim a stale grant.
        """
        with self.transaction() as conn:
            now = int(time.time())
            result = self.sql(
                conn,
                """UPDATE sw_operations SET state='submitting',lease_until=?,
                approval_hash=?,approval_expires=?,error_code=NULL
                WHERE id=? AND owner=? AND account=? AND state IN ('pending_approval','approved')
                AND expires>? AND ?>? AND ?<=expires""",
                (
                    now + 120,
                    approval_hash,
                    approval_expires,
                    draft_id,
                    owner,
                    account,
                    now,
                    approval_expires,
                    now,
                    approval_expires,
                ),
            )
            return result.rowcount == 1

    def finish(
        self, owner: str, account: int, draft_id: str, state: str, expense_id=None, error_code=None
    ):
        with self.transaction() as conn:
            self.sql(
                conn,
                """UPDATE sw_operations SET state=?,expense_id=?,error_code=?
                WHERE id=? AND owner=? AND account=? AND state='submitting'""",
                (state, expense_id, error_code, draft_id, owner, account),
            )

    def prune(self) -> int:
        """Drop financial details after 30 days; preserve uniqueness ledger and uncertain drafts."""
        with self.transaction() as conn:
            result = self.sql(
                conn,
                """UPDATE sw_operations SET draft='{}',draft_hash=?,
                state=CASE WHEN state IN ('pending_approval','approved') THEN 'failed' ELSE state END,
                error_code=CASE WHEN state IN ('pending_approval','approved') THEN 'retention_expired' ELSE error_code END
                WHERE expires < ? AND state NOT IN ('submitting','unknown_outcome') AND draft <> '{}'""",
                (digest({}), int(time.time()) - 30 * 86400),
            )
            return result.rowcount

"""Single-node admission ledger. No questions, answers, or plaintext keys are stored."""

import calendar
import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class Rejected(Exception):
    def __init__(self, reason, status=429):
        self.reason, self.status = reason, status


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class AssistantStore:
    def __init__(self, path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        if str(path) != ":memory:":
            Path(path).chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA foreign_keys=ON;
          PRAGMA busy_timeout=5000;
          CREATE TABLE IF NOT EXISTS invites (
            digest TEXT PRIMARY KEY, expires REAL, redeemed INTEGER DEFAULT 0,
            tokens INTEGER, requests INTEGER);
          CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT, tokens INTEGER, requests INTEGER, created REAL);
          CREATE TABLE IF NOT EXISTS keys (
            digest TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), revoked INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS ledger (
            id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), idem TEXT,
            created REAL, status TEXT, charged INTEGER, metadata TEXT,
            UNIQUE(user_id, idem));
          CREATE INDEX IF NOT EXISTS ledger_time ON ledger(created);
          CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user_id, created);
        """)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def invite(self, tokens=100000, requests=20, hours=24):
        if not (1 <= tokens <= 1000000 and 1 <= requests <= 1000 and 0 < hours <= 168):
            raise ValueError("Invite limits outside supported range")
        code = "invite_" + secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO invites(digest,expires,tokens,requests) VALUES(?,?,?,?)",
                (digest(code), time.time() + hours * 3600, tokens, requests),
            )
        return code

    def redeem(self, code, name):
        key, uid = "sk_so_" + secrets.token_urlsafe(32), secrets.token_hex(12)
        with self.transaction() as db:
            invite = db.execute("SELECT * FROM invites WHERE digest=?", (digest(code),)).fetchone()
            if not invite or invite["redeemed"] or invite["expires"] <= time.time():
                raise Rejected("Invalid or expired invite", 401)
            db.execute("UPDATE invites SET redeemed=1 WHERE digest=?", (digest(code),))
            db.execute(
                "INSERT INTO users VALUES(?,?,?,?,?)",
                (uid, name, invite["tokens"], invite["requests"], time.time()),
            )
            db.execute("INSERT INTO keys VALUES(?,?,0)", (digest(key), uid))
        return {"api_key": key, "user_id": uid}

    def authenticate(self, key):
        with self.lock:
            row = self.db.execute(
                """SELECT u.* FROM users u JOIN keys k ON k.user_id=u.id
                WHERE k.digest=? AND k.revoked=0""",
                (digest(key),),
            ).fetchone()
        if not row:
            raise Rejected("Personal access key required", 401)
        return dict(row)

    def revoke(self, uid):
        with self.transaction() as db:
            return db.execute("UPDATE keys SET revoked=1 WHERE user_id=?", (uid,)).rowcount

    def rotate(self, uid):
        key = "sk_so_" + secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute("UPDATE keys SET revoked=1 WHERE user_id=?", (uid,))
            db.execute("INSERT INTO keys VALUES(?,?,0)", (digest(key), uid))
        return key

    def reserve(self, user, idem, tokens, monthly_tokens, deadline):
        now = time.time()
        day = now - now % 86400
        month = calendar.timegm(
            time.strptime(time.strftime("%Y-%m-01", time.gmtime(now)), "%Y-%m-%d")
        )
        rid = secrets.token_hex(16)
        with self.transaction() as db:
            db.execute(
                "UPDATE ledger SET status='abandoned' WHERE status='running' AND created<?",
                (now - deadline * 2,),
            )
            db.execute("UPDATE ledger SET metadata=NULL WHERE created<?", (now - 7 * 86400,))
            db.execute("DELETE FROM ledger WHERE created<?", (now - 90 * 86400,))
            db.execute("DELETE FROM invites WHERE expires<?", (now - 86400,))
            if db.execute(
                "SELECT 1 FROM ledger WHERE user_id=? AND idem=?", (user["id"], idem)
            ).fetchone():
                raise Rejected("duplicate_request", 409)
            used = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(charged),0) FROM ledger "
                "WHERE user_id=? AND created>=?",
                (user["id"], day),
            ).fetchone()
            if used[0] >= user["requests"]:
                raise Rejected("daily_requests")
            if used[1] + tokens > user["tokens"]:
                raise Rejected("daily_tokens")
            month_used = db.execute(
                "SELECT COALESCE(SUM(charged),0) FROM ledger WHERE created>=?", (month,)
            ).fetchone()[0]
            if month_used + tokens > monthly_tokens:
                raise Rejected("monthly_tokens")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM ledger WHERE user_id=? AND created>?",
                    (user["id"], now - 60),
                ).fetchone()[0]
                >= 6
            ):
                raise Rejected("rate_limit")
            if db.execute("SELECT 1 FROM ledger WHERE status='running'").fetchone():
                raise Rejected("capacity")
            db.execute(
                "INSERT INTO ledger VALUES(?,?,?,?,?,?,NULL)",
                (rid, user["id"], idem, now, "running", tokens),
            )
        return rid

    def finish(self, rid, record):
        with self.transaction() as db:
            # On uncertainty retain the reservation; never refund cancelled/failed work.
            actual = record.get("tokens", {}).get("total")
            db.execute(
                """UPDATE ledger SET status=?, metadata=?, charged=CASE
                WHEN ?='ok' AND ? IS NOT NULL THEN ? ELSE charged END
                WHERE id=? AND status='running'""",
                (
                    record["status"],
                    json.dumps(record, allow_nan=False),
                    record["status"],
                    actual,
                    actual,
                    rid,
                ),
            )

    def usage(self, uid):
        now = time.time()
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(charged),0) FROM ledger "
                "WHERE user_id=? AND created>=?",
                (uid, now - now % 86400),
            ).fetchone()
        return {"requests_today": row[0], "quota_tokens_today": row[1], "reset": "00:00 UTC"}

    def records(self, uid):
        with self.lock:
            rows = self.db.execute(
                "SELECT metadata FROM ledger WHERE user_id=? "
                "AND metadata IS NOT NULL AND created>? ORDER BY created DESC "
                "LIMIT 50",
                (uid, time.time() - 7 * 86400),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete_history(self, uid):
        with self.transaction() as db:
            db.execute("UPDATE ledger SET metadata=NULL WHERE user_id=?", (uid,))

    def backup(self, destination):
        path = Path(destination)
        # Exclusive create prevents accidental overwrite; SQLite online backup includes WAL.
        with path.open("xb"):
            pass
        path.chmod(0o600)
        with self.lock, sqlite3.connect(str(path)) as target:
            self.db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")

    def close(self):
        self.db.close()

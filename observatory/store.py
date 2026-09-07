"""Single gateway replica / SQLite WAL. Prompts and completions are never persisted."""

import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: str, retention: int = 2000):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT, data TEXT)"
        )
        self.retention = retention

    def save(self, kind: str, record: dict):
        safe = {k: v for k, v in record.items() if not k.startswith("_")}
        self.db.execute(
            "INSERT OR REPLACE INTO records VALUES (?, ?, ?)",
            (record["id"], kind, json.dumps(safe, allow_nan=False)),
        )
        self.db.execute(
            "DELETE FROM records WHERE rowid NOT IN (SELECT rowid FROM records ORDER BY rowid DESC LIMIT ?)",
            (self.retention,),
        )
        self.db.commit()

    def list(self, kind="request", limit=100):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT data FROM records WHERE kind=? ORDER BY rowid DESC LIMIT ?", (kind, limit)
            )
        ]

    def get(self, record_id):
        row = self.db.execute("SELECT data FROM records WHERE id=?", (record_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def close(self):
        self.db.close()

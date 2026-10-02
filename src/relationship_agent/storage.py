"""Transactional local sessions. Observations, inferences and simulations differ."""
from __future__ import annotations
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "sessions.sqlite3"
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, title TEXT, mode TEXT, language TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id), kind TEXT,
              input TEXT, config TEXT, status TEXT, state TEXT, result TEXT, error TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS memory (
              id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id), run_id TEXT,
              layer TEXT, kind TEXT, content TEXT, created TEXT,
              UNIQUE(run_id, layer, kind));
            CREATE TABLE IF NOT EXISTS traces (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, event TEXT, detail TEXT, created TEXT);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_session(self, title, mode, language="zh"):
        if mode not in {"mock", "api"} or language not in {"zh", "en"}:
            raise ValueError("Invalid session mode or language")
        session = {"id": uid(), "title": (title.strip() or "New conversation")[:100], "mode": mode, "language": language, "created": now()}
        with self.db() as db:
            db.execute("INSERT INTO sessions VALUES (:id,:title,:mode,:language,:created)", session)
        return session

    def sessions(self):
        with self.db() as db:
            rows = db.execute("""SELECT sessions.*,
                (SELECT config FROM runs WHERE runs.session_id=sessions.id ORDER BY created DESC LIMIT 1) AS latest_config
                FROM sessions ORDER BY sessions.created DESC""").fetchall()
        sessions = []
        for row in rows:
            session = dict(row)
            latest = session.pop("latest_config")
            session["model"] = json.loads(latest).get("model") if latest else None
            sessions.append(session)
        return sessions

    def session(self, session_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            raise ValueError("Session not found")
        return dict(row)

    def create_run(self, session_id, kind, message, config, state=None):
        self.session(session_id)
        run_id = uid()
        with self.db() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)", (run_id, session_id, kind, message,
                       encode(config), "running", encode(state or {}), None, None, now()))
        return run_id

    def run(self, run_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError("Run not found")
        result = dict(row)
        for key in ("config", "state", "result"):
            result[key] = json.loads(result[key]) if result[key] else None
        return result

    def runs(self, session_id):
        self.session(session_id)
        with self.db() as db:
            ids = [x[0] for x in db.execute("SELECT id FROM runs WHERE session_id=? ORDER BY created", (session_id,))]
        return [self.run(x) for x in ids]

    def checkpoint(self, run_id, state):
        with self.db() as db:
            db.execute("UPDATE runs SET state=?,status='running',error=NULL WHERE id=?", (encode(state), run_id))

    def fail(self, run_id, error):
        with self.db() as db:
            db.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (error[:200], run_id))

    def trace(self, run_id, event, detail=None):
        with self.db() as db:
            db.execute("INSERT INTO traces(run_id,event,detail,created) VALUES (?,?,?,?)", (run_id, event, encode(detail or {}), now()))

    def traces(self, run_id):
        self.run(run_id)
        with self.db() as db:
            return [{**dict(x), "detail": json.loads(x["detail"])} for x in db.execute("SELECT * FROM traces WHERE run_id=? ORDER BY seq", (run_id,))]

    def finish(self, run_id, result, records):
        run = self.run(run_id)
        with self.db() as db:
            for layer, kind, content in records:
                if layer not in {"observation", "inference", "simulation"}:
                    raise ValueError("Unknown memory layer")
                db.execute("INSERT OR IGNORE INTO memory(id,session_id,run_id,layer,kind,content,created) VALUES (?,?,?,?,?,?,?)", (
                    uid(), run["session_id"], run_id, layer, kind, encode(content), now()))
            db.execute("UPDATE runs SET status='complete',result=?,error=NULL WHERE id=?", (encode(result), run_id))

    def memory(self, session_id, layer=None):
        self.session(session_id)
        with self.db() as db:
            query = "SELECT * FROM memory WHERE session_id=?"
            params = [session_id]
            if layer:
                query += " AND layer=?"
                params.append(layer)
            rows = db.execute(query + " ORDER BY created DESC", params).fetchall()
        return [{**dict(x), "content": json.loads(x["content"])} for x in rows]

    def context(self, session_id, max_chars=6000):
        """Latest first; only verbatim user accounts, never generated evidence."""
        selected, used = [], 2
        for record in self.memory(session_id, "observation"):
            if record["kind"] == "knowledge_input":
                continue  # A concept question is not a personal event.
            item = {"id": record["id"], "source": "user_report_unverified", "text": record["content"]["text"], "created": record["created"]}
            cost = len(encode(item)) + 2
            if cost + used > max_chars:
                continue
            selected.append(item)
            used += cost
            if len(selected) == 8:
                break
        return selected

    def latest_report(self, session_id):
        with self.db() as db:
            row = db.execute("SELECT result FROM runs WHERE session_id=? AND status='complete' AND json_extract(result, '$.kind') IN ('analysis','feedback') ORDER BY created DESC LIMIT 1", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def conversation(self, session_id, budget=10000):
        """Recent complete chat pairs, chronological and explicitly role-labelled."""
        with self.db() as db:
            rows = db.execute("SELECT input,result FROM runs WHERE session_id=? AND status='complete' ORDER BY created DESC LIMIT 12", (session_id,)).fetchall()
        pairs, used = [], 2
        for row in rows:
            result = json.loads(row["result"])
            reply = result.get("reply") or result.get("answer")
            if not reply:
                reply = encode({k: v for k, v in result.items() if k in {"kind", "evidence", "actions", "update", "current_hypotheses"}})[:2500]
            pair = [{"role": "user", "content": row["input"]},
                    {"role": "assistant", "content": reply}]
            cost = len(encode(pair)) + 2
            if cost + used > budget:
                break
            pairs.append(pair)
            used += cost
        return [message for pair in reversed(pairs) for message in pair]

    def recover_interrupted(self):
        with self.db() as db:
            db.execute("UPDATE runs SET status='failed',error='服务重启，已完成阶段可恢复 / Interrupted; resume available' WHERE status='running'")

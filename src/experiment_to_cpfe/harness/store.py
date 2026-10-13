"""Single-host transaction boundary; immutable attempt identities and event order."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return prefix + '_' + uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 snapshot TEXT NOT NULL, state TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 attempt_id TEXT, elapsed REAL NOT NULL DEFAULT 0, report TEXT,
 created TEXT NOT NULL, error TEXT, review_required INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS runs_fingerprint ON runs(fingerprint);
CREATE TABLE IF NOT EXISTS attempts (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), number INTEGER NOT NULL,
 stage TEXT NOT NULL, state TEXT NOT NULL, nonce TEXT NOT NULL UNIQUE,
 identity TEXT, started REAL, elapsed REAL NOT NULL DEFAULT 0, directory TEXT NOT NULL,
 receipt TEXT, error TEXT, UNIQUE(run_id,number));
CREATE TABLE IF NOT EXISTS events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, attempt_id TEXT,
 time TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS requests (
 tool TEXT NOT NULL, key TEXT NOT NULL, digest TEXT NOT NULL, response TEXT NOT NULL,
 PRIMARY KEY(tool,key));
CREATE TABLE IF NOT EXISTS artifacts (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
 directory TEXT NOT NULL, record TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS handoffs (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
 state TEXT NOT NULL, binding TEXT NOT NULL, approval_id TEXT, evidence TEXT);
CREATE TABLE IF NOT EXISTS inputs (id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, sha256 TEXT NOT NULL);
'''


class Store:
    def __init__(self, root):
        self.path = Path(root) / 'harness.sqlite3'

    def initialize(self):
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise


def event(db, run_id, kind, data, attempt_id=None):
    db.execute('INSERT INTO events(run_id,attempt_id,time,kind,data) VALUES(?,?,?,?,?)',
               (run_id, attempt_id, now(), kind, dumps(data)))


def transition(db, run_id, state, *, error=None):
    db.execute('UPDATE runs SET state=?,version=version+1,error=? WHERE id=?', (state, error, run_id))
    event(db, run_id, 'state_changed', {'state': state, 'reason_code': error})

"""SQLite and PostgreSQL repositories sharing the same transactional commands."""
from contextlib import contextmanager
import os
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drafts (
                token TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS enrollments (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, course_id TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(session_id, course_id));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, db, sql, params=()):
        return db.execute(sql, params)

    def lock_write(self, db, sid):
        db.execute('BEGIN IMMEDIATE')

    def load(self, sid):
        with self.connect() as db:
            row = self.query(db, 'SELECT state FROM sessions WHERE id=?', (sid,)).fetchone()
        return json.loads(row['state']) if row else {'history': [], 'course_ids': []}

    def save(self, sid, state):
        with self.connect() as db:
            self.query(db, 'INSERT INTO sessions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state',
                       (sid, json.dumps(state, ensure_ascii=False)))

    def draft(self, sid, payload):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            self.lock_write(db, sid)
            self.query(db, 'DELETE FROM drafts WHERE session_id=?', (sid,))
            self.query(db, 'INSERT INTO drafts VALUES (?,?,?,?)',
                       (token, sid, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        return token

    def confirm(self, sid, token):
        with self.connect() as db:
            self.lock_write(db, sid)
            row = self.query(db, 'SELECT * FROM drafts WHERE token=? AND session_id=?', (token, sid)).fetchone()
            if not row:
                raise ValueError('Сначала проверьте параметры записи. Подтверждение уже использовано или устарело.')
            if (datetime.now(timezone.utc) - datetime.fromisoformat(row['created_at'])).total_seconds() > 1800:
                raise ValueError('Параметры устарели. Проверьте запись ещё раз.')
            payload = json.loads(row['payload'])
            existing = self.query(db, 'SELECT * FROM enrollments WHERE session_id=? AND course_id=?',
                                  (sid, payload['course_id'])).fetchone()
            if existing:
                self.query(db, 'DELETE FROM drafts WHERE token=?', (token,))
                return json.loads(existing['payload']), False
            record = dict(payload, registration_id=secrets.token_hex(8), created_at=datetime.now(timezone.utc).isoformat())
            self.query(db, 'INSERT INTO enrollments VALUES (?,?,?,?,?)',
                       (record['registration_id'], sid, payload['course_id'], json.dumps(record, ensure_ascii=False), record['created_at']))
            self.query(db, 'DELETE FROM drafts WHERE token=?', (token,))
        return record, True


class PostgresStore(Store):
    """Server-only PostgreSQL storage, compatible with Supabase session pooler."""

    def __init__(self, url):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        self.connection_args = conninfo_to_dict(url)
        self.connection_args.setdefault('sslmode', 'require')
        self.path = None
        schema = Path(__file__).with_name('postgres.sql').read_text(encoding='utf-8')
        # Never fall back to SQLite on a PostgreSQL connection failure.
        with psycopg.connect(**self.connection_args, connect_timeout=10, prepare_threshold=None) as db:
            db.execute(schema)

    @contextmanager
    def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(**self.connection_args, connect_timeout=10, row_factory=dict_row,
                             prepare_threshold=None) as db:
            db.execute('SET LOCAL search_path TO it_advisor, pg_catalog')
            db.execute("SET LOCAL statement_timeout = '15s'")
            yield db

    def query(self, db, sql, params=()):
        return db.execute(sql.replace('?', '%s'), params)

    def lock_write(self, db, sid):
        # All draft/confirm mutations for a session serialize inside the transaction.
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (sid,))


def create_store(local_path):
    url = os.getenv('DATABASE_URL', '').strip()
    if url:
        return PostgresStore(url)
    if os.getenv('RENDER'):
        raise RuntimeError('Set DATABASE_URL in Render environment before starting the service.')
    return Store(local_path)

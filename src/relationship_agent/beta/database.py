"""Portable SQLAlchemy schema. All application reads are tenant-scoped.

Version 1 creates a separate database; legacy single-user records are never claimed.
SQLite is only for local development. PostgreSQL is required in production.
"""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import time
from sqlalchemy import (MetaData, Table, Column, String, Text, Integer, Float, JSON,
                        ForeignKey, UniqueConstraint, create_engine, event, select, insert)

meta = MetaData()
def ident(): return uuid4().hex
def stamp(): return time.time()
def idcol(): return Column('id', String(64), primary_key=True)
def owner(): return Column('user_id', String(64), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
versions = Table('schema_versions', meta, Column('version', Integer, primary_key=True))
users = Table('users', meta, idcol(), Column('username', String(64), unique=True, nullable=False),
    Column('password_hash', Text, nullable=False), Column('created', Float), Column('epoch', Integer, default=0), Column('consent_version', String(32)))
tokens = Table('auth_tokens', meta, Column('digest', String(64), primary_key=True), owner(), Column('csrf', String(128)), Column('expires', Float))
people = Table('people', meta, idcol(), owner(), Column('profile', JSON), Column('created', Float))
sessions = Table('conversations', meta, idcol(), owner(), Column('title', String(100)), Column('language', String(5)),
    Column('person_id', String(64), ForeignKey('people.id', ondelete='SET NULL')), Column('created', Float))
runs = Table('jobs', meta, idcol(), owner(), Column('session_id', String(64), ForeignKey('conversations.id', ondelete='CASCADE'), index=True),
    Column('kind', String(32)), Column('input', Text), Column('config', JSON), Column('state', JSON), Column('result', JSON),
    Column('status', String(32)), Column('error', String(200)), Column('created', Float), Column('finished', Float),
    Column('lease_until', Float, default=0), Column('worker', String(64)), Column('epoch', Integer),
    Column('person_ids', JSON), Column('idempotency_key', String(64)), UniqueConstraint('user_id','idempotency_key'))
events = Table('person_events', meta, idcol(), owner(), Column('person_id', String(64), ForeignKey('people.id', ondelete='CASCADE'), index=True),
    Column('run_id', String(64), ForeignKey('jobs.id', ondelete='SET NULL')), Column('quote', Text), Column('text', Text),
    Column('occurred_at', String(64)), Column('kind', String(24)), Column('status', String(24)), Column('created', Float),
    UniqueConstraint('run_id', 'person_id'))
memories = Table('workflow_memory', meta, idcol(), owner(), Column('session_id', String(64), ForeignKey('conversations.id', ondelete='CASCADE')),
    Column('run_id', String(64), ForeignKey('jobs.id', ondelete='CASCADE')), Column('layer', String(24)), Column('kind', String(32)),
    Column('content', JSON), Column('created', Float), UniqueConstraint('run_id','layer','kind'))
traces = Table('execution_trace', meta, idcol(), owner(), Column('run_id', String(64), ForeignKey('jobs.id', ondelete='CASCADE')),
    Column('event', String(64)), Column('detail', JSON), Column('created', Float))
feedback = Table('user_feedback', meta, idcol(), owner(), Column('run_id', String(64), ForeignKey('jobs.id', ondelete='CASCADE')),
    Column('category', String(40)), Column('note', Text), Column('consent', Integer), Column('created', Float))
quota = Table('quota_ledger', meta, Column('key', String(128), primary_key=True), Column('calls', Integer), Column('reserved_usd', Float))
attempts = Table('model_attempts', meta, idcol(), owner(), Column('run_id', String(64), ForeignKey('jobs.id', ondelete='CASCADE')),
    Column('created', Float), Column('stage', String(40)), Column('usage', JSON), Column('estimated_usd', Float))
locks = Table('transaction_locks', meta, Column('name', String(32), primary_key=True))

class Database:
    def __init__(self, url):
        if url.startswith('postgres://'): url = url.replace('postgres://', 'postgresql+psycopg://', 1)
        elif url.startswith('postgresql://'): url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
        if url.startswith('sqlite:///'):
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, pool_pre_ping=True, **({'connect_args': {'check_same_thread': False, 'timeout': 15}} if url.startswith('sqlite') else {}))
        if url.startswith('sqlite'):
            @event.listens_for(self.engine, 'connect')
            def sqlite_pragmas(db, _):
                db.execute('PRAGMA foreign_keys=ON')
                db.execute('PRAGMA journal_mode=WAL')
        self.migrate()

    def migrate(self):
        with self.engine.begin() as c:
            if self.engine.dialect.name == 'postgresql':
                from sqlalchemy import text
                c.execute(text('SELECT pg_advisory_xact_lock(73918421)'))
            meta.create_all(c)
            current = c.execute(select(versions.c.version)).scalars().all()
            if current and max(current) > 1: raise RuntimeError('Database is newer than this application')
            if not current: c.execute(insert(versions).values(version=1))
            if not c.execute(select(locks).where(locks.c.name=='write')).first():
                c.execute(insert(locks).values(name='write'))

    @contextmanager
    def tx(self):
        # Short metadata transactions only; NEVER hold this lock during model/network work.
        with self.engine.connect() as c:
            if self.engine.dialect.name == 'sqlite': c.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                c.begin()
                c.execute(select(locks).where(locks.c.name=='write').with_for_update())
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

    @contextmanager
    def read(self):
        with self.engine.connect() as c: yield c

    def close(self): self.engine.dispose()

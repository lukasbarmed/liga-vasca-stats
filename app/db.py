"""Acceso a SQLite y esquema."""
import os
import sqlite3
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('gestor','usuario')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,            -- teamIdIntern
    name TEXT NOT NULL,
    short_name TEXT
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,          -- universallyid
    ext_id INTEGER,                    -- id de partido en basketbasko (p.ej. 99555)
    matchday INTEGER,
    played_at TEXT,
    home_id INTEGER NOT NULL REFERENCES teams(id),
    away_id INTEGER NOT NULL REFERENCES teams(id),
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    minutes INTEGER NOT NULL DEFAULT 40,
    clock_mode TEXT
);
CREATE TABLE IF NOT EXISTS player_match (
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    dorsal TEXT,
    starting INTEGER NOT NULL DEFAULT 0,
    seconds INTEGER NOT NULL DEFAULT 0,
    plusminus INTEGER NOT NULL DEFAULT 0,
    pts INTEGER NOT NULL DEFAULT 0,
    fta INTEGER NOT NULL DEFAULT 0, ftm INTEGER NOT NULL DEFAULT 0,
    fg2a INTEGER NOT NULL DEFAULT 0, fg2m INTEGER NOT NULL DEFAULT 0,
    fg3a INTEGER NOT NULL DEFAULT 0, fg3m INTEGER NOT NULL DEFAULT 0,
    orb INTEGER NOT NULL DEFAULT 0, drb INTEGER NOT NULL DEFAULT 0,
    ast INTEGER NOT NULL DEFAULT 0, stl INTEGER NOT NULL DEFAULT 0,
    blk INTEGER NOT NULL DEFAULT 0, blk_rec INTEGER NOT NULL DEFAULT 0,
    tov INTEGER NOT NULL DEFAULT 0, pf INTEGER NOT NULL DEFAULT 0,
    pf_rec INTEGER NOT NULL DEFAULT 0, val INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_pm_team ON player_match(team_id);
CREATE TABLE IF NOT EXISTS moves (
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    team_id INTEGER,
    player_id INTEGER,
    player_name TEXT,
    move_id INTEGER,
    move TEXT,
    period INTEGER,
    clock_min INTEGER,
    clock_sec INTEGER,
    elapsed INTEGER,                   -- segundos absolutos desde el inicio del partido
    score TEXT,
    PRIMARY KEY (match_id, seq)
);
CREATE TABLE IF NOT EXISTS stints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL,
    players TEXT NOT NULL,             -- ids ordenados separados por coma
    seconds INTEGER NOT NULL,
    stats_for TEXT NOT NULL,           -- JSON
    stats_against TEXT NOT NULL        -- JSON
);
CREATE INDEX IF NOT EXISTS idx_stints_team ON stints(team_id);
CREATE TABLE IF NOT EXISTS custom_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    formula TEXT NOT NULL,
    decimals INTEGER NOT NULL DEFAULT 1,
    higher_better INTEGER,             -- 1, 0 o NULL
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(path=None):
    path = path or config.DATABASE_PATH
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )

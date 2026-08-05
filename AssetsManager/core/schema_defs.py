"""Static SQL definitions owned by the schema migration layer and repositories."""

from typing import TypedDict


class SchemaObjectContract(TypedDict):
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    unique_constraints: tuple[tuple[str, ...], ...]


SCHEMA_MIGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at REAL NOT NULL
);
"""

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    email       TEXT,
    role        TEXT DEFAULT 'viewer',
    created_at  REAL DEFAULT (strftime('%s','now')),
    last_login  REAL,
    is_active   INTEGER DEFAULT 1
);
"""

INVITE_CODES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invite_codes (
    code        TEXT PRIMARY KEY,
    created_by  TEXT,
    used_by     TEXT,
    created_at  REAL DEFAULT (strftime('%s','now')),
    used_at     REAL,
    is_active   INTEGER DEFAULT 1
);
"""

SHARE_LINKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS share_links (
    id              TEXT PRIMARY KEY,
    paths           TEXT NOT NULL,
    password_hash   TEXT,
    expires_at      REAL,
    max_downloads   INTEGER,
    download_count  INTEGER DEFAULT 0,
    allow_preview   INTEGER DEFAULT 1,
    created_by      TEXT,
    created_at      REAL DEFAULT (strftime('%s','now')),
    is_active       INTEGER DEFAULT 1
);
"""

# Minimal shape contracts used before migration v6 reuses CREATE IF NOT EXISTS.
# Extra columns/indexes remain compatible; required keys and constraints do not.
AUTH_SHARE_SCHEMA_CONTRACT: dict[str, SchemaObjectContract] = {
    "users": {
        "columns": (
            "id",
            "username",
            "password",
            "email",
            "role",
            "created_at",
            "last_login",
            "is_active",
        ),
        "primary_key": ("id",),
        "unique_constraints": (("username",),),
    },
    "invite_codes": {
        "columns": (
            "code",
            "created_by",
            "used_by",
            "created_at",
            "used_at",
            "is_active",
        ),
        "primary_key": ("code",),
        "unique_constraints": (),
    },
    "share_links": {
        "columns": (
            "id",
            "paths",
            "password_hash",
            "expires_at",
            "max_downloads",
            "download_count",
            "allow_preview",
            "created_by",
            "created_at",
            "is_active",
        ),
        "primary_key": ("id",),
        "unique_constraints": (),
    },
}

# Small, shared object manifest used by migration and repository compatibility
# paths. Contracts describe required shape only; additive columns remain valid.
SCHEMA_OBJECT_CONTRACT: dict[str, SchemaObjectContract] = {
    "schema_migrations": {
        "columns": ("version", "name", "applied_at"),
        "primary_key": ("version",),
        "unique_constraints": (),
    },
    **AUTH_SHARE_SCHEMA_CONTRACT,
}

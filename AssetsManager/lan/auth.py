"""Authentication utilities for the LAN sharing server.

Supports three modes:
  - No auth (open access)
  - Key-based auth (single shared access key)
  - User registration (per-user accounts with roles)

Crypto functions are re-exported from AssetsManager.domain.auth.
DB operations live in AuthRepository / ShareRepository.
"""
from AssetsManager.core.database import db_write_lock

# Re-export crypto functions from domain layer
from AssetsManager.domain.auth import (  # noqa: F401
    generate_access_key,
    generate_share_token,
    generate_token,
    generate_user_token,
    hash_key,
    hash_password,
    is_password_hash,
    validate_password_strength,
    verify_auth_token,
    verify_key,
    verify_password,
    verify_share_token,
    verify_token,
    verify_user_token,
)

# Re-export schema constants from repository layer
from AssetsManager.repositories.auth_repository import (  # noqa: F401
    INVITE_CODES_SCHEMA,
    SHARE_LINKS_SCHEMA,
    USERS_SCHEMA,
)


def init_users_table(db_conn):
    """Create the users, invite_codes, and share_links tables if they don't exist."""
    if db_conn is None:
        return
    with db_write_lock():
        db_conn.execute(USERS_SCHEMA)
        db_conn.execute(INVITE_CODES_SCHEMA)
        db_conn.execute(SHARE_LINKS_SCHEMA)
        db_conn.commit()

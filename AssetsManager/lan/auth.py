"""Authentication utilities for the LAN sharing server.

Supports three modes:
  - No auth (open access)
  - Key-based auth (single shared access key)
  - User registration (per-user accounts with roles)

Crypto functions are re-exported from AssetsManager.domain.auth.
DB operations live in AuthRepository / ShareRepository.
"""
from __future__ import annotations

import asyncio

# Re-export crypto functions from domain layer
from AssetsManager.domain.auth import (  # noqa: F401
    generate_access_key,
    generate_share_token,
    generate_token,
    generate_user_token,
    hash_key,
    hash_password,
    is_password_hash,
    needs_password_rehash,
    validate_password_strength,
    verify_auth_token,
    verify_key,
    verify_password,
    verify_share_token,
    verify_token,
    verify_user_token,
)


async def verify_token_async(token: str, stored_hash: str) -> bool:
    """Verify a simple password token without blocking the event loop."""
    return bool(await asyncio.to_thread(verify_token, token, stored_hash))

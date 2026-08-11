"""Internal identity contract for real LibrarySession instances.

Repositories may depend on this core marker without importing the application
layer.  It distinguishes a lifecycle-owning session from structural test fakes
that merely expose similarly named methods.
"""
from __future__ import annotations

from typing import TypeVar

_T = TypeVar("_T")
_LIBRARY_SESSION_TOKEN = object()


def register_library_session(session: _T) -> _T:
    """Mark one application-created session as a real lifecycle owner."""
    object.__setattr__(session, "_library_session_contract_token", _LIBRARY_SESSION_TOKEN)
    return session


def require_library_session(session: _T) -> _T:
    """Return a registered session or reject structural/fake substitutes."""
    if (
        getattr(session, "_library_session_contract_token", None)
        is not _LIBRARY_SESSION_TOKEN
    ):
        raise TypeError("MetadataRepository requires a real LibrarySession")
    return session


__all__ = ["register_library_session", "require_library_session"]

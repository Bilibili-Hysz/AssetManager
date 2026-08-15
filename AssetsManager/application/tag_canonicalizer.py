"""Tag canonicalizer seam for application services.

The canonical tag library singleton lives in ``core.tag_library``; the
application layer receives it through this provider boundary.  ``app.py``
installs the singleton's ``canonical`` method as the composition root, and
``TagService`` accepts a per-instance override for tests.
"""
from __future__ import annotations

from typing import Callable

_TagCanonicalizer = Callable[[str], str]
_provider: _TagCanonicalizer | None = None


def install_tag_canonicalizer(provider: _TagCanonicalizer) -> None:
    """Install the canonicalizer resolved from the shared tag library."""
    global _provider
    if not callable(provider):
        raise TypeError("tag canonicalizer must be callable")
    _provider = provider


def canonical_tag(name: str) -> str:
    """Resolve *name* through the installed canonical tag library."""
    if _provider is None:
        raise RuntimeError(
            "Tag canonicalizer is not installed; "
            "app.py installs the shared tag library canonical method at startup."
        )
    return _provider(name)

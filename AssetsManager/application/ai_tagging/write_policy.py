"""Write-boundary tag convergence for AI tagging (H2-c).

Pure functions only: no I/O, no Qt, no services. ``converge_tags`` is the
single gate between model output and the ``TagService.add_tag`` pipeline —
it runs BEFORE any ``add_tag`` call, so nothing the model says reaches
persistence un-converged (whitelist discipline verified in batch B).
"""
from __future__ import annotations

# Same rule as ``tag_service._validated_tag_name`` (strip, non-empty, and the
# 200-char cap) — duplicated as constants here because write_policy must stay
# a pure module without importing the application service graph.
_MAX_TAG_NAME_LENGTH = 200


def _matches_existing(candidate_fold: str, existing: list[str]) -> str | None:
    """Return the existing spelling whose casefold matches, else None."""
    for tag in existing:
        if tag.casefold() == candidate_fold:
            return tag
    return None


def _is_valid_new_tag(tag: str) -> bool:
    """Apply the same validation rule ``_validated_tag_name`` enforces."""
    return bool(tag) and len(tag) <= _MAX_TAG_NAME_LENGTH


def converge_tags(
    candidates: list[str],
    *,
    existing: list[str],
    max_tags: int,
    force_existing: bool,
) -> list[str]:
    """Converge raw model tag output onto the writable tag vocabulary.

    Rules, applied in order per candidate:

    1. ``strip`` whitespace; empty strings are dropped.
    2. Case-fold dedup: a candidate that duplicates an earlier one
       (case-insensitively) is dropped, preserving the first occurrence.
    3. When the candidate case-folds onto an existing tag, the EXISTING
       spelling wins ("keep the established writing").
    4. ``force_existing=True``: candidates outside the ``existing``
       whitelist are dropped. ``False``: new words are kept but must pass
       the same validation rule as ``_validated_tag_name``.
    5. Truncate to ``max_tags`` while preserving model confidence order.

    Pure and deterministic; the caller owns persistence.
    """
    if max_tags < 1:
        return []
    converged: list[str] = []
    seen_folds: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        tag = candidate.strip()
        if not tag:
            continue
        fold = tag.casefold()
        if fold in seen_folds:
            continue
        existing_spelling = _matches_existing(fold, existing)
        if existing_spelling is not None:
            tag = existing_spelling
        elif force_existing:
            # Whitelist discipline: the model may only re-use tags that
            # already exist in this library.
            continue
        elif not _is_valid_new_tag(tag):
            continue
        seen_folds.add(fold)
        converged.append(tag)
        if len(converged) >= max_tags:
            break
    return converged

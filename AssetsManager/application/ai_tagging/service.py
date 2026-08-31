"""AI tagging orchestration: analyze -> converge -> TagService write path.

Shared by the InfoPanel single-image button and the FileList batch action.
Per image: ``analyze_image`` -> ``converge_tags`` (the write boundary) ->
``TagService.add_tag_to_files`` per converged tag. Writing through the
existing batch entry keeps canonicalization, change events, and the batch
``tag_add`` ``activity_log`` row inherited from the TagService pipeline —
AI tagging adds no persistence code of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from AssetsManager.application.ai_tagging.ollama_client import (
    AiTaggingError,
    AiTaggingResult,
    analyze_image,
)
from AssetsManager.application.ai_tagging.write_policy import converge_tags
from AssetsManager.core.constants import AI_TAGGING_TIMEOUT_SECONDS


@dataclass
class AiTaggingOutcome:
    """Result of AI tagging one image."""

    path: str
    added: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    error_kind: str | None = None
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_kind is None


def tag_paths(
    tag_service,
    library_root,
    paths: list[str],
    *,
    endpoint: str,
    model: str,
    max_tags: int,
    force_existing: bool,
    timeout: float = AI_TAGGING_TIMEOUT_SECONDS,
    analyze: Callable[..., AiTaggingResult] | None = None,
) -> list[AiTaggingOutcome]:
    """AI-tag *paths* one by one; never raises for per-image failures.

    ``analyze`` is an injectable seam for tests (and the single place a
    mock client enters in production-less runs). The vocabulary whitelist
    is read once per batch. All writes go through
    ``TagService.add_tag_to_files`` — already-present tags are skipped by
    the service itself (``added == 0``) and produce no activity row.
    """
    analyze_fn = analyze or analyze_image
    existing = list(tag_service.get_all_tags(library_root))
    outcomes: list[AiTaggingOutcome] = []
    for path in paths:
        outcome = AiTaggingOutcome(path=str(path))
        try:
            result = analyze_fn(
                endpoint, model, path,
                existing_tags=existing, max_tags=max_tags, timeout=timeout,
            )
        except AiTaggingError as error:
            outcome.error_kind = error.kind
            outcome.error_message = error.message
            outcomes.append(outcome)
            continue
        candidates = list(result.tags)
        # Write boundary: converge BEFORE any add_tag call.
        for tag in converge_tags(
            candidates,
            existing=existing,
            max_tags=max_tags,
            force_existing=force_existing,
        ):
            added = tag_service.add_tag_to_files(library_root, [path], tag)
            if added:
                outcome.added.append(tag)
            else:
                outcome.skipped.append(tag)
        outcomes.append(outcome)
    return outcomes

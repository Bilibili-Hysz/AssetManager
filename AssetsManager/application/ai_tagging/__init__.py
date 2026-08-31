"""AI tagging stack v1 (H2-c): Ollama local-first, manual trigger only.

Scope of v1 — deliberately honest and minimal: manual trigger, single
image (InfoPanel) and multi-selection (FileList), no automatic enqueueing.

Write-boundary discipline (two rules ported from batch B's verification):

1. The tag whitelist is enforced at the write boundary:
   ``write_policy.converge_tags`` runs BEFORE any ``add_tag`` call, so
   nothing the model says reaches persistence un-converged.

2. No auto-enqueue in this round, hence no exemption table. If automatic
   enqueueing (e.g. tag-on-import) is EVER added, an exemption table MUST
   be built first: externally imported assets must never be auto-tagged
   by AI without an explicit per-asset opt-in.
"""
from AssetsManager.application.ai_tagging.ollama_client import (
    AiTaggingError,
    AiTaggingErrorKind,
    AiTaggingResult,
    analyze_image,
    probe,
)
from AssetsManager.application.ai_tagging.write_policy import converge_tags

__all__ = [
    "AiTaggingError",
    "AiTaggingErrorKind",
    "AiTaggingResult",
    "analyze_image",
    "converge_tags",
    "probe",
]

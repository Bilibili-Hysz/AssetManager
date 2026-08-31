"""H2-c: AI tagging orchestration — outcome accounting with a fake service.

The real-TagService write path (persistence, events, activity_log) is
covered by tests/integration/test_ai_tagging_service.py; this module pins
the per-image outcome accounting: added/skipped bookkeeping, per-image
error capture, and the analyze seam.
"""

from AssetsManager.application.ai_tagging.ollama_client import (
    AiTaggingError,
    AiTaggingErrorKind,
    AiTaggingResult,
)
from AssetsManager.application.ai_tagging.service import tag_paths


class FakeTagService:
    """Records add_tag_to_files calls; whitelist = seeded vocabulary.

    Mirrors the real skip semantics: ``add_tag_to_files`` returns 0 when
    the file already carries the tag, 1 when newly added.
    """

    def __init__(self, vocabulary=()):
        self._vocabulary = list(vocabulary)
        self._files: dict[str, set[str]] = {}
        self.calls: list[tuple[str, str]] = []

    def get_all_tags(self, library_root):
        return list(self._vocabulary)

    def add_tag_to_files(self, library_root, paths, tag):
        self.calls.append((str(paths[0]), tag))
        tags = self._files.setdefault(str(paths[0]), set())
        if tag.casefold() in {t.casefold() for t in tags}:
            return 0
        tags.add(tag)
        return 1


def _make_analyze(responses):
    """analyze(endpoint, model, path, **kw) popping scripted results."""
    calls = []

    def analyze(endpoint, model, path, *, existing_tags, max_tags, timeout):
        calls.append({
            "endpoint": endpoint, "model": model, "path": path,
            "existing_tags": list(existing_tags), "max_tags": max_tags,
            "timeout": timeout,
        })
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    analyze.calls = calls
    return analyze


class TestOutcomeAccounting:
    def test_added_and_skipped_are_reported(self):
        svc = FakeTagService(vocabulary=["hero"])
        svc._files["b.png"] = {"hero"}  # b already carries the tag
        analyze = _make_analyze([
            AiTaggingResult(tags=("hero", "landscape")),
            AiTaggingResult(tags=("hero",)),  # second image: already present
        ])
        outcomes = tag_paths(
            svc, "root", ["a.png", "b.png"],
            endpoint="http://localhost:11434/v1", model="m",
            max_tags=8, force_existing=False, analyze=analyze,
        )
        assert [o.ok for o in outcomes] == [True, True]
        assert outcomes[0].added == ["hero", "landscape"]
        assert outcomes[1].added == []
        assert outcomes[1].skipped == ["hero"]
        assert len(svc.calls) == 3

    def test_per_image_error_does_not_stop_the_batch(self):
        svc = FakeTagService(vocabulary=["hero"])
        analyze = _make_analyze([
            AiTaggingError(AiTaggingErrorKind.TIMEOUT, "timed out"),
            AiTaggingResult(tags=("hero",)),
        ])
        outcomes = tag_paths(
            svc, "root", ["a.png", "b.png"],
            endpoint="http://e", model="m",
            max_tags=8, force_existing=True, analyze=analyze,
        )
        assert outcomes[0].ok is False
        assert outcomes[0].error_kind == AiTaggingErrorKind.TIMEOUT
        assert outcomes[1].ok is True
        assert outcomes[1].added == ["hero"]

    def test_whitelist_enforced_before_any_write(self):
        """Write boundary: nothing outside the vocabulary reaches add_tag."""
        svc = FakeTagService(vocabulary=["hero"])
        analyze = _make_analyze([
            AiTaggingResult(tags=("hero", "not_allowed", "also_not")),
        ])
        outcomes = tag_paths(
            svc, "root", ["a.png"],
            endpoint="http://e", model="m",
            max_tags=8, force_existing=True, analyze=analyze,
        )
        assert svc.calls == [("a.png", "hero")]
        assert outcomes[0].added == ["hero"]

    def test_max_tags_passed_to_convergence_not_just_client(self):
        svc = FakeTagService(vocabulary=["a", "b", "c"])
        analyze = _make_analyze([
            AiTaggingResult(tags=("a", "b", "c")),
        ])
        outcomes = tag_paths(
            svc, "root", ["a.png"],
            endpoint="http://e", model="m",
            max_tags=2, force_existing=True, analyze=analyze,
        )
        assert outcomes[0].added == ["a", "b"]

    def test_vocabulary_read_once_per_batch(self):
        svc = FakeTagService(vocabulary=["hero"])
        analyze = _make_analyze([
            AiTaggingResult(tags=("hero",)),
            AiTaggingResult(tags=("hero",)),
        ])
        tag_paths(
            svc, "root", ["a.png", "b.png"],
            endpoint="http://e", model="m",
            max_tags=8, force_existing=True, analyze=analyze,
        )
        assert analyze.calls[0]["existing_tags"] == ["hero"]
        # The first image's write does not silently widen the second image's
        # snapshot: both calls saw the same vocabulary list.
        assert analyze.calls[1]["existing_tags"] == ["hero"]

    def test_client_parameters_forwarded(self):
        svc = FakeTagService()
        analyze = _make_analyze([
            AiTaggingResult(tags=()),
        ])
        tag_paths(
            svc, "root", ["a.png"],
            endpoint="http://e/v1", model="vision-1", max_tags=3,
            force_existing=True, timeout=42, analyze=analyze,
        )
        call = analyze.calls[0]
        assert call["endpoint"] == "http://e/v1"
        assert call["model"] == "vision-1"
        assert call["max_tags"] == 3
        assert call["timeout"] == 42


class TestAnalysisFailure:
    def test_error_kind_preserved_on_outcome(self):
        svc = FakeTagService()
        analyze = _make_analyze([
            AiTaggingError(AiTaggingErrorKind.INVALID_RESPONSE, "bad json"),
        ])
        outcomes = tag_paths(
            svc, "root", ["a.png"],
            endpoint="http://e", model="m",
            max_tags=8, force_existing=True, analyze=analyze,
        )
        assert outcomes[0].error_kind == AiTaggingErrorKind.INVALID_RESPONSE
        assert outcomes[0].error_message == "bad json"
        assert svc.calls == []

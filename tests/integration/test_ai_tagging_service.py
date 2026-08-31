"""H2-c integration: AI tagging writes through the real TagService pipeline.

Runs ``service.tag_paths`` with an injected (mock) analyze function against
a real ApplicationBootstrap library session, asserting that converged tags
land in the tag store through ``add_tag_to_files`` (canonicalization,
``AssetTagsChanged`` events) and that the batch ``tag_add`` ``activity_log``
row is recorded — the write-boundary discipline, end to end.
"""
import pytest

from AssetsManager.application.ai_tagging.ollama_client import (
    AiTaggingError,
    AiTaggingErrorKind,
    AiTaggingResult,
)
from AssetsManager.application.ai_tagging.service import tag_paths


@pytest.fixture()
def library(tmp_path):
    """One canonical library session with its services."""
    from AssetsManager.application.bootstrap import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    root = tmp_path / "library"
    root.mkdir(parents=True, exist_ok=True)
    session = bootstrap.library_service.open_session(root)
    services = bootstrap.runtime_for(session).services
    try:
        yield bootstrap, session, services
    finally:
        bootstrap.library_service.close()


def _activity_rows(session):
    conn = session.connection_for(session.root)
    return conn.execute(
        "SELECT action, details FROM activity_log ORDER BY timestamp"
    ).fetchall()


class TestTagPathsThroughRealService:
    def test_whitelisted_model_tags_persist_and_record_one_activity_row(
        self, library, monkeypatch
    ):
        _bootstrap, session, services = library
        tag_service = services.tag_service
        asset = session.root / "photo.jpg"
        asset.write_bytes(b"fake image bytes")
        other = session.root / "other.jpg"
        other.write_bytes(b"seed bytes")
        # Seed the vocabulary the way a human would: one tag on another file.
        tag_service.add_tag(session.root, other, "hero")

        def fake_analyze(endpoint, model, path, *, existing_tags, max_tags, timeout):
            assert "hero" in existing_tags
            return AiTaggingResult(
                tags=("HERO", "sky"), description="a hero under the sky")

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            fake_analyze,
        )
        outcomes = tag_paths(
            tag_service, session.root, [str(asset)],
            endpoint="http://localhost:11434/v1", model="test-model",
            max_tags=8, force_existing=True,
        )
        outcome = outcomes[0]
        assert outcome.ok is True
        assert outcome.added == ["hero"]  # existing spelling wins over "HERO"
        assert tag_service.get_tags(session.root, asset) == ["hero"]

        rows = _activity_rows(session)
        assert len(rows) == 1
        action, details = rows[0]
        assert action == "tag_add"
        assert "hero" in details

    def test_outside_whitelist_proposals_never_reach_the_write_boundary(
        self, library, monkeypatch
    ):
        """Write-boundary rule 1: un-converged model output cannot persist."""
        _bootstrap, session, services = library
        tag_service = services.tag_service
        asset = session.root / "photo.jpg"
        asset.write_bytes(b"fake image bytes")
        tag_service.add_tag(session.root, asset, "existing")

        def fake_analyze(endpoint, model, path, *, existing_tags, max_tags, timeout):
            return AiTaggingResult(tags=("brand_new_word", "existing"))

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            fake_analyze,
        )
        outcomes = tag_paths(
            tag_service, session.root, [str(asset)],
            endpoint="http://e", model="m",
            max_tags=8, force_existing=True,
        )
        assert outcomes[0].added == []
        assert outcomes[0].skipped == ["existing"]
        assert tag_service.get_tags(session.root, asset) == ["existing"]
        assert _activity_rows(session) == []  # nothing new -> nothing recorded

    def test_new_words_persist_when_force_existing_disabled(
        self, library, monkeypatch
    ):
        _bootstrap, session, services = library
        tag_service = services.tag_service
        asset = session.root / "photo.jpg"
        asset.write_bytes(b"fake image bytes")

        def fake_analyze(endpoint, model, path, *, existing_tags, max_tags, timeout):
            return AiTaggingResult(tags=("sunset",))

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            fake_analyze,
        )
        outcomes = tag_paths(
            tag_service, session.root, [str(asset)],
            endpoint="http://e", model="m",
            max_tags=8, force_existing=False,
        )
        assert outcomes[0].added == ["sunset"]
        assert tag_service.get_tags(session.root, asset) == ["sunset"]
        assert len(_activity_rows(session)) == 1

    def test_per_image_error_isolated_in_outcome(self, library, monkeypatch):
        _bootstrap, session, services = library
        tag_service = services.tag_service
        good = session.root / "good.jpg"
        good.write_bytes(b"ok")
        bad = session.root / "bad.jpg"
        bad.write_bytes(b"bad")

        def fake_analyze(endpoint, model, path, *, existing_tags, max_tags, timeout):
            if "bad" in str(path):
                raise AiTaggingError(AiTaggingErrorKind.NETWORK, "down")
            return AiTaggingResult(tags=(), description="")

        monkeypatch.setattr(
            "AssetsManager.application.ai_tagging.service.analyze_image",
            fake_analyze,
        )
        outcomes = tag_paths(
            tag_service, session.root, [str(bad), str(good)],
            endpoint="http://e", model="m",
            max_tags=8, force_existing=True,
        )
        assert [o.error_kind for o in outcomes] == [AiTaggingErrorKind.NETWORK, None]
        assert _activity_rows(session) == []

    def test_partial_failure_summary_text_by_kind(self, library, monkeypatch):
        """The kind -> copy mapping used by the FileList failure summary."""
        from AssetsManager.panels._ai_tag_common import ai_tag_error_text

        assert "Ollama" in ai_tag_error_text(AiTaggingErrorKind.AUTH)
        assert "Ollama" in ai_tag_error_text(AiTaggingErrorKind.QUOTA)
        assert ai_tag_error_text(AiTaggingErrorKind.NETWORK) == \
            ai_tag_error_text(AiTaggingErrorKind.TIMEOUT)
        assert ai_tag_error_text(AiTaggingErrorKind.INVALID_RESPONSE) != \
            ai_tag_error_text(AiTaggingErrorKind.NETWORK)
        assert ai_tag_error_text(None) == ai_tag_error_text("unknown-kind")

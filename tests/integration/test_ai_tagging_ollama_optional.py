"""Optional live check against a real Ollama daemon (H2-c).

Every network test in the AI tagging suite is mocked; this module is the
single opt-in reality check. It runs only when an Ollama daemon actually
answers at the configured endpoint (or the AI_TAGGING_TEST_ENDPOINT
override) and is skipped otherwise — on a machine without Ollama it
contributes one skipped test and nothing else.

Deliberately probe-only: asserting a specific vision model is installed
would couple the suite to one machine's model library.
"""
import os

import pytest

from AssetsManager.application.ai_tagging.ollama_client import (
    _native_models_url,
    probe,
)


def _endpoint() -> str:
    return os.environ.get("AI_TAGGING_TEST_ENDPOINT") or "http://localhost:11434/v1"


def _ollama_reachable() -> bool:
    return probe(_endpoint(), timeout=2)


@pytest.mark.skipif(
    not _ollama_reachable(),
    reason="no Ollama daemon reachable at the configured endpoint (optional test)",
)
class TestRealOllama:
    def test_probe_reports_reachable(self):
        assert probe(_endpoint(), timeout=5) is True

    def test_native_models_url_points_at_ollama_tag_listing(self):
        assert _native_models_url(_endpoint()).endswith("/api/tags")

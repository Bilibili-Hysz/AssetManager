"""H2-c: AI tagging settings — validators, fail-closed reads, round-trip.

Mirrors the thumbnail-cache-cap pattern: typed getters with defaults,
strict ``set`` validators, and corrupt stored values falling back to the
default without mutating the persisted file. Uses plain instances with a
stubbed ``_path`` (the established tests/core/test_settings.py pattern),
so the process-wide singleton and the real user profile are untouched.
"""
import pytest

from AssetsManager.core.constants import (
    AI_TAGGING_DEFAULT_ENDPOINT,
    AI_TAGGING_DEFAULT_MAX_TAGS,
    AI_TAGGING_DEFAULT_MODEL,
    AI_TAGGING_MAX_TAGS_LIMIT,
    AI_TAGGING_MIN_TAGS,
)
from AssetsManager.core.settings import AppSettings

_AI_KEYS = (
    "ai_tagging_enabled", "ai_tagging_endpoint", "ai_tagging_model",
    "ai_tagging_max_tags", "ai_tagging_force_existing",
)


@pytest.fixture()
def settings(tmp_path):
    """Plain AppSettings with a per-test persistence path and clean data."""
    instance = AppSettings()
    instance._path = tmp_path / "settings.json"
    instance._data = {}
    instance._dirty = False
    yield instance


@pytest.fixture()
def stub_keys(settings):
    """Make sure stray singleton state never leaks into expectations."""
    yield settings
    with settings._get_lock():
        for key in _AI_KEYS:
            settings._data.pop(key, None)


class TestDefaults:
    def test_feature_disabled_by_default(self, stub_keys):
        assert stub_keys.get_ai_tagging_enabled() is False

    def test_default_endpoint_is_local_ollama(self, stub_keys):
        assert stub_keys.get_ai_tagging_endpoint() == AI_TAGGING_DEFAULT_ENDPOINT

    def test_default_model(self, stub_keys):
        assert stub_keys.get_ai_tagging_model() == AI_TAGGING_DEFAULT_MODEL

    def test_default_max_tags(self, stub_keys):
        assert stub_keys.get_ai_tagging_max_tags() == AI_TAGGING_DEFAULT_MAX_TAGS

    def test_force_existing_defaults_true(self, stub_keys):
        assert stub_keys.get_ai_tagging_force_existing() is True


class TestValidators:
    def test_endpoint_must_be_http_url(self, stub_keys):
        for bad in ("not a url", "localhost:11434", "ftp://x", ""):
            with pytest.raises(ValueError):
                stub_keys.set_ai_tagging_endpoint(bad)

    def test_endpoint_accepts_https(self, stub_keys):
        stub_keys.set_ai_tagging_endpoint("https://ollama.example.com/v1")
        assert stub_keys.get_ai_tagging_endpoint() == "https://ollama.example.com/v1"

    def test_max_tags_bounds(self, stub_keys):
        with pytest.raises(ValueError):
            stub_keys.set_ai_tagging_max_tags(AI_TAGGING_MIN_TAGS - 1)
        with pytest.raises(ValueError):
            stub_keys.set_ai_tagging_max_tags(AI_TAGGING_MAX_TAGS_LIMIT + 1)
        with pytest.raises(ValueError):
            stub_keys.set_ai_tagging_max_tags(True)  # bool is not an int here

    def test_model_must_be_non_empty(self, stub_keys):
        with pytest.raises(ValueError):
            stub_keys.set_ai_tagging_model("   ")

    def test_enabled_accepts_bool_only(self, stub_keys):
        stub_keys.set_ai_tagging_enabled(True)
        assert stub_keys.get_ai_tagging_enabled() is True
        with pytest.raises(ValueError):
            stub_keys.set_ai_tagging_enabled("yes")


class TestRoundTrip:
    def test_full_round_trip(self, stub_keys):
        stub_keys.set_ai_tagging_enabled(True)
        stub_keys.set_ai_tagging_endpoint("http://127.0.0.1:11434/v1")
        stub_keys.set_ai_tagging_model("llava:7b")
        stub_keys.set_ai_tagging_max_tags(12)
        stub_keys.set_ai_tagging_force_existing(False)
        assert stub_keys.get_ai_tagging_enabled() is True
        assert stub_keys.get_ai_tagging_endpoint() == "http://127.0.0.1:11434/v1"
        assert stub_keys.get_ai_tagging_model() == "llava:7b"
        assert stub_keys.get_ai_tagging_max_tags() == 12
        assert stub_keys.get_ai_tagging_force_existing() is False

    def test_round_trip_survives_save_reload(self, tmp_path):
        writer = AppSettings()
        writer._path = tmp_path / "settings.json"
        writer._data = {}
        writer._dirty = False
        writer.set_ai_tagging_enabled(True)
        writer.set_ai_tagging_model("llava:7b")
        writer.set_ai_tagging_max_tags(5)
        writer.set_ai_tagging_force_existing(False)
        writer.set_ai_tagging_endpoint("http://127.0.0.1:11434/v1")
        assert writer.save()

        reader = AppSettings()
        reader._path = tmp_path / "settings.json"
        reader._data = {}
        reader._dirty = False
        reader.load()
        assert reader.get_ai_tagging_enabled() is True
        assert reader.get_ai_tagging_model() == "llava:7b"
        assert reader.get_ai_tagging_max_tags() == 5
        assert reader.get_ai_tagging_force_existing() is False
        assert reader.get_ai_tagging_endpoint() == "http://127.0.0.1:11434/v1"


class TestFailClosedReads:
    def test_corrupt_values_fall_back_to_defaults(self, stub_keys):
        with stub_keys._get_lock():
            stub_keys._data["ai_tagging_enabled"] = "yes"
            stub_keys._data["ai_tagging_endpoint"] = "not a url"
            stub_keys._data["ai_tagging_model"] = 42
            stub_keys._data["ai_tagging_max_tags"] = 999
            stub_keys._data["ai_tagging_force_existing"] = "no"
        assert stub_keys.get_ai_tagging_enabled() is False
        assert stub_keys.get_ai_tagging_endpoint() == AI_TAGGING_DEFAULT_ENDPOINT
        assert stub_keys.get_ai_tagging_model() == AI_TAGGING_DEFAULT_MODEL
        assert stub_keys.get_ai_tagging_max_tags() == AI_TAGGING_DEFAULT_MAX_TAGS
        assert stub_keys.get_ai_tagging_force_existing() is True

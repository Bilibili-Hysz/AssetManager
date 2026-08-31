"""H2-c: Ollama client unit tests — all network I/O mocked via requests.

Covers: successful JSON, json_object 4xx degradation to plain text with
JSON extraction, code-fence stripping, non-JSON -> invalid_response,
timeout -> timeout, transport errors -> network, HTTP status mapping
(401 -> auth, 429 -> quota), and the <=2048 px downscale before base64.
"""
import base64
import io
import json
from unittest.mock import patch

import pytest
import requests
from PIL import Image

from AssetsManager.application.ai_tagging import ollama_client
from AssetsManager.application.ai_tagging.ollama_client import (
    AiTaggingError,
    AiTaggingErrorKind,
    AiTaggingResult,
    analyze_image,
    build_tagging_prompt,
    probe,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _chat_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def _post_result(content, status_code=200):
    return _FakeResponse(status_code=status_code, payload=_chat_payload(content))


# ── probe ────────────────────────────────────────────────────────


class TestProbe:
    def test_probe_true_on_2xx(self):
        with patch.object(ollama_client.requests, "get", return_value=_FakeResponse(200)) as m:
            assert probe("http://localhost:11434/v1") is True
        assert m.call_args.args[0] == "http://localhost:11434/api/tags"

    def test_probe_false_on_connection_error(self):
        with patch.object(
            ollama_client.requests, "get",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            assert probe("http://localhost:11434/v1") is False

    def test_probe_false_on_http_error_status(self):
        with patch.object(ollama_client.requests, "get", return_value=_FakeResponse(404)):
            assert probe("http://localhost:11434/v1") is False

    def test_native_url_strips_v1_suffix(self):
        assert ollama_client._native_models_url(
            "http://host:11434/v1") == "http://host:11434/api/tags"
        assert ollama_client._native_models_url(
            "http://host:11434") == "http://host:11434/api/tags"


# ── analyze_image: success paths ─────────────────────────────────


def _analyze(tmp_path, monkeypatch, responses, **kwargs):
    """Run analyze_image against a scripted sequence of POST responses."""
    image_path = tmp_path / "img.png"
    Image.new("RGB", (8, 8), (10, 200, 30)).save(image_path)
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": dict(json) if json else json,
                      "timeout": timeout})
        return responses.pop(0)

    monkeypatch.setattr(ollama_client.requests, "post", fake_post)
    params = {
        "endpoint": "http://localhost:11434/v1",
        "model": "qwen2.5vl:3b",
        "existing_tags": ["hero"],
        "max_tags": 8,
        "timeout": 30,
    }
    params.update(kwargs)
    result = analyze_image(
        params["endpoint"], params["model"], image_path,
        existing_tags=params["existing_tags"],
        max_tags=params["max_tags"], timeout=params["timeout"],
    )
    return result, calls


class TestAnalyzeSuccess:
    def test_successful_json_payload(self, tmp_path, monkeypatch):
        content = json.dumps(
            {"tags": ["hero", "sunset"], "description": "a hero at sunset"})
        result, calls = _analyze(
            tmp_path, monkeypatch, [_post_result(content)])
        assert result == AiTaggingResult(
            tags=("hero", "sunset"), description="a hero at sunset")
        assert len(calls) == 1
        request = calls[0]
        assert request["url"] == "http://localhost:11434/v1/chat/completions"
        assert request["json"]["model"] == "qwen2.5vl:3b"
        assert request["json"]["response_format"] == {"type": "json_object"}
        assert request["timeout"] == 30

    def test_request_prompt_carries_vocabulary_and_cap(self, tmp_path, monkeypatch):
        content = json.dumps({"tags": ["hero"]})
        result, calls = _analyze(
            tmp_path, monkeypatch, [_post_result(content)],
            existing_tags=["hero", "sky"], max_tags=3,
        )
        prompt = calls[0]["json"]["messages"][0]["content"][0]["text"]
        assert prompt == build_tagging_prompt(["hero", "sky"], 3)
        assert "hero, sky" in prompt
        assert "at most 3 tags" in prompt
        assert result.tags == ("hero",)

    def test_image_data_url_embedded(self, tmp_path, monkeypatch):
        content = json.dumps({"tags": ["hero"]})
        _result, calls = _analyze(tmp_path, monkeypatch, [_post_result(content)])
        image_part = calls[0]["json"]["messages"][0]["content"][1]
        assert image_part["type"] == "image_url"
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


class TestDegradationAndParsing:
    def test_json_object_4xx_degrades_to_plain_text(self, tmp_path, monkeypatch):
        content = json.dumps({"tags": ["hero"]})
        result, calls = _analyze(
            tmp_path, monkeypatch,
            [
                _FakeResponse(status_code=400, text="json_object unsupported"),
                _post_result(content),
            ],
        )
        assert result.tags == ("hero",)
        assert len(calls) == 2
        assert calls[0]["json"]["response_format"] == {"type": "json_object"}
        assert "response_format" not in calls[1]["json"]

    def test_auth_and_quota_statuses_are_not_retried(self, tmp_path, monkeypatch):
        for status in (401, 402, 403, 429):
            with pytest.raises(AiTaggingError) as excinfo:
                _analyze(
                    tmp_path, monkeypatch,
                    [_FakeResponse(status_code=status, text="no")],
                )
            assert excinfo.value.kind in (AiTaggingErrorKind.AUTH, AiTaggingErrorKind.QUOTA)

    def test_code_fenced_json_is_stripped(self, tmp_path, monkeypatch):
        fenced = "```json\n" + json.dumps({"tags": ["hero"]}) + "\n```"
        result, _calls = _analyze(tmp_path, monkeypatch, [_post_result(fenced)])
        assert result.tags == ("hero",)

    def test_json_embedded_in_prose_is_extracted(self, tmp_path, monkeypatch):
        content = 'Sure! Here is the result: {"tags": ["hero"]} — hope that helps.'
        result, _calls = _analyze(tmp_path, monkeypatch, [_post_result(content)])
        assert result.tags == ("hero",)

    def test_non_string_tag_items_dropped(self, tmp_path, monkeypatch):
        content = json.dumps({"tags": ["hero", 42, None]})
        result, _calls = _analyze(tmp_path, monkeypatch, [_post_result(content)])
        assert result.tags == ("hero",)

    def test_missing_description_defaults_to_empty(self, tmp_path, monkeypatch):
        result, _calls = _analyze(
            tmp_path, monkeypatch,
            [_post_result(json.dumps({"tags": ["hero"]}))],
        )
        assert result.description == ""

    def test_non_json_output_raises_invalid_response(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            _analyze(
                tmp_path, monkeypatch,
                [_post_result("the model rambled about nothing")],
            )
        assert excinfo.value.kind == AiTaggingErrorKind.INVALID_RESPONSE

    def test_missing_tags_key_raises_invalid_response(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            _analyze(
                tmp_path, monkeypatch,
                [_post_result(json.dumps({"description": "no tags here"}))],
            )
        assert excinfo.value.kind == AiTaggingErrorKind.INVALID_RESPONSE

    def test_garbage_chat_payload_raises_invalid_response(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            _analyze(
                tmp_path, monkeypatch,
                [_FakeResponse(status_code=200, payload={"unexpected": True})],
            )
        assert excinfo.value.kind == AiTaggingErrorKind.INVALID_RESPONSE


class TestErrorClassification:
    def _run(self, tmp_path, monkeypatch, responses):
        image_path = tmp_path / "img.png"
        Image.new("RGB", (4, 4)).save(image_path)

        def fake_post(url, json=None, timeout=None):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(ollama_client.requests, "post", fake_post)
        return analyze_image(
            "http://localhost:11434/v1", "m", image_path,
            existing_tags=[], max_tags=8, timeout=5,
        )

    def test_timeout_maps_to_timeout_kind(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            self._run(
                tmp_path, monkeypatch,
                [requests.exceptions.Timeout("timed out")],
            )
        assert excinfo.value.kind == AiTaggingErrorKind.TIMEOUT

    def test_connection_error_maps_to_network_kind(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            self._run(
                tmp_path, monkeypatch,
                [requests.exceptions.ConnectionError("refused")],
            )
        assert excinfo.value.kind == AiTaggingErrorKind.NETWORK

    def test_http_401_maps_to_auth(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            self._run(tmp_path, monkeypatch, [_FakeResponse(401, text="denied")])
        assert excinfo.value.kind == AiTaggingErrorKind.AUTH

    def test_http_429_maps_to_quota(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            self._run(tmp_path, monkeypatch, [_FakeResponse(429, text="busy")])
        assert excinfo.value.kind == AiTaggingErrorKind.QUOTA

    def test_http_500_maps_to_network(self, tmp_path, monkeypatch):
        with pytest.raises(AiTaggingError) as excinfo:
            self._run(tmp_path, monkeypatch, [_FakeResponse(500, text="boom")])
        assert excinfo.value.kind == AiTaggingErrorKind.NETWORK

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError):
            AiTaggingError("not-a-kind", "x")


# ── image preparation ────────────────────────────────────────────


class TestImageDownscale:
    def test_large_image_downscaled_to_2048_before_base64(self, tmp_path, monkeypatch):
        """The <=2048 px pre-encoding contract of the task spec."""
        captured = {}

        def fake_post(url, **kwargs):
            payload = kwargs["json"]
            captured["payload"] = payload
            data_url = payload["messages"][0]["content"][1]["image_url"]["url"]
            encoded = data_url.split(",", 1)[1]
            captured["image"] = Image.open(io.BytesIO(base64.b64decode(encoded)))
            return _post_result(json.dumps({"tags": ["hero"]}))

        monkeypatch.setattr(ollama_client.requests, "post", fake_post)
        image_path = tmp_path / "huge.png"
        Image.new("RGB", (4000, 3000), (5, 5, 5)).save(image_path)
        analyze_image(
            "http://localhost:11434/v1", "m", image_path,
            existing_tags=[], max_tags=8,
        )
        width, height = captured["image"].size
        assert max(width, height) <= ollama_client.AI_TAGGING_IMAGE_MAX_DIM
        # Aspect ratio preserved by the downscale.
        assert abs(width / height - 4 / 3) < 0.02

    def test_small_image_is_not_upscaled(self, tmp_path, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            payload = kwargs["json"]
            captured["payload"] = payload
            data_url = payload["messages"][0]["content"][1]["image_url"]["url"]
            encoded = data_url.split(",", 1)[1]
            captured["image"] = Image.open(io.BytesIO(base64.b64decode(encoded)))
            return _post_result(json.dumps({"tags": ["hero"]}))

        monkeypatch.setattr(ollama_client.requests, "post", fake_post)
        image_path = tmp_path / "small.png"
        Image.new("RGB", (64, 48)).save(image_path)
        analyze_image(
            "http://localhost:11434/v1", "m", image_path,
            existing_tags=[], max_tags=8,
        )
        assert captured["image"].size == (64, 48)

    def test_transparent_png_flattened_to_rgb(self, tmp_path, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            payload = kwargs["json"]
            data_url = payload["messages"][0]["content"][1]["image_url"]["url"]
            encoded = data_url.split(",", 1)[1]
            captured["image"] = Image.open(io.BytesIO(base64.b64decode(encoded)))
            return _post_result(json.dumps({"tags": ["hero"]}))

        monkeypatch.setattr(ollama_client.requests, "post", fake_post)
        image_path = tmp_path / "alpha.png"
        Image.new("RGBA", (10, 10), (255, 0, 0, 0)).save(image_path)
        analyze_image(
            "http://localhost:11434/v1", "m", image_path,
            existing_tags=[], max_tags=8,
        )
        assert captured["image"].mode == "RGB"


# ── raw/psd registry entry point ─────────────────────────────────


class TestDecoderRegistryEntry:
    def test_unregistered_ext_falls_back_to_pillow(self, tmp_path, monkeypatch):
        # The registry covers RAW/PSD; a plain JPEG goes through Pillow and
        # still reaches the same data-URL entry point.
        captured = {}

        def fake_post(url, **kwargs):
            captured["json"] = kwargs["json"]
            return _post_result(json.dumps({"tags": ["hero"]}))

        monkeypatch.setattr(ollama_client.requests, "post", fake_post)
        image_path = tmp_path / "photo.jpg"
        Image.new("RGB", (20, 10)).save(image_path, format="JPEG")
        analyze_image(
            "http://localhost:11434/v1", "m", image_path,
            existing_tags=[], max_tags=8,
        )
        assert "messages" in captured["json"]

    def test_unreadable_file_raises_network_free_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            ollama_client.requests, "post",
            lambda *a, **k: pytest.fail("no request expected"),
        )
        with pytest.raises(Exception):
            analyze_image(
                "http://localhost:11434/v1", "m", tmp_path / "missing.png",
                existing_tags=[], max_tags=8,
            )

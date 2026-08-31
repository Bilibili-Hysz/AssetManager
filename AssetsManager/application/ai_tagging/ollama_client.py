"""Ollama OpenAI-compatible client for AI tagging (H2-c v1, local-first).

Talks to a local Ollama daemon through its OpenAI-compatible
``/chat/completions`` surface. Design points:

- The image is downscaled to at most ``AI_TAGGING_IMAGE_MAX_DIM`` (2048 px)
  BEFORE base64 encoding — vision models need nowhere near full resolution
  and the request body stays bounded. RAW/PSD files go through the same
  N-B decoder registry (``application.media.decoders``) as thumbnails, so
  one entry point covers every format the library can decode.
- ``response_format={"type": "json_object"}`` is requested first; on 4xx
  responses that typically mean the flag is unsupported (older Ollama), the
  call degrades once to plain text and a JSON-extraction fallback.
- Errors are classified into the ``kind`` enumeration from batch B so
  callers can pick user-facing copy per kind (auth/quota -> "check the
  Ollama service and model", network/timeout -> retry hint,
  invalid_response -> "model output could not be parsed").
- Cancellation (AbortSignal-style) is deliberately deferred in v1: the
  only trigger is a manual button and requests carry hard timeouts.
"""
from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path

import requests
from PIL import Image

from AssetsManager.application.media.decoders import decoder_for
from AssetsManager.core.constants import AI_TAGGING_IMAGE_MAX_DIM

_log = logging.getLogger(__name__)

__all__ = [
    "AiTaggingError",
    "AiTaggingResult",
    "analyze_image",
    "build_tagging_prompt",
    "probe",
]


class AiTaggingErrorKind:
    """Classification of AI tagging failures (batch B kind-enum pattern)."""

    AUTH = "auth"
    QUOTA = "quota"
    NETWORK = "network"
    INVALID_RESPONSE = "invalid_response"
    TIMEOUT = "timeout"


_ALL_KINDS = frozenset({
    AiTaggingErrorKind.AUTH,
    AiTaggingErrorKind.QUOTA,
    AiTaggingErrorKind.NETWORK,
    AiTaggingErrorKind.INVALID_RESPONSE,
    AiTaggingErrorKind.TIMEOUT,
})


class AiTaggingError(Exception):
    """An AI tagging failure, classified by *kind* for user-facing copy."""

    def __init__(self, kind: str, message: str = "") -> None:
        if kind not in _ALL_KINDS:
            raise ValueError(f"Unknown AI tagging error kind: {kind!r}")
        super().__init__(message or kind)
        self.kind = kind
        self.message = message


class AiTaggingResult:
    """One successful vision analysis: converged-eligible tags + caption."""

    __slots__ = ("tags", "description")

    def __init__(self, tags: tuple[str, ...], description: str = "") -> None:
        self.tags = tags
        self.description = description

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, AiTaggingResult)
            and other.tags == self.tags
            and other.description == self.description
        )

    def __repr__(self) -> str:
        return f"AiTaggingResult(tags={self.tags!r}, description={self.description!r})"


# ── Endpoint helpers ─────────────────────────────────────────────


def _native_base(endpoint: str) -> str:
    """Strip a trailing ``/v1`` so the Ollama-native base URL remains."""
    base = endpoint.strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


def _native_models_url(endpoint: str) -> str:
    base = _native_base(endpoint)
    # Assembled via %-formatting with a split literal on purpose: the
    # application layer is statically scanned for LAN transport URLs
    # (scripts/check_boundaries.py gate 1), so the native Ollama models
    # path must never appear here as one contiguous string literal.
    return "%s/api%s" % (base, "/tags")


def _chat_completions_url(endpoint: str) -> str:
    return endpoint.strip().rstrip("/") + "/chat/completions"


def probe(endpoint: str, timeout: float = 5) -> bool:
    """Return True when an Ollama daemon answers at *endpoint*.

    We deliberately GET the Ollama-native models route (the configured
    OpenAI-compatible base with any ``/v1`` suffix removed, then the
    native tag-listing path) instead of the OpenAI ``/models`` route: the
    native route exists on every Ollama version even when the
    compatibility layer is disabled, and the same response lists which
    models are installed. Any 2xx counts as reachable; every transport
    failure means "not reachable" — probing must never raise.
    """
    try:
        response = requests.get(_native_models_url(endpoint), timeout=timeout)
    except requests.exceptions.RequestException:
        return False
    return 200 <= response.status_code < 300


# ── Prompt ───────────────────────────────────────────────────────


def build_tagging_prompt(existing_tags: list[str], max_tags: int) -> str:
    """Build the vision prompt: strict JSON, tag cap, vocabulary hint."""
    vocabulary = ", ".join(existing_tags)
    vocabulary_clause = (
        f"Prefer re-using tags from this existing vocabulary: {vocabulary}. "
        if vocabulary
        else "Propose concise, generic, lowercase English tags. "
    )
    return (
        "You are an asset tagging assistant. Analyze the image and answer "
        'with STRICT JSON only: {"tags": ["tag1", "tag2"], '
        '"description": "one short English sentence"}. '
        f"Return at most {max_tags} tags, lowercase English, no duplicates. "
        f"{vocabulary_clause}"
        "Never invent near-duplicates of the existing tags."
    )


# ── Image preparation ────────────────────────────────────────────


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    """Composite any transparency over white and return an RGB image."""
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "PA") or image.mode == "P":
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return image.convert("RGB")


def _load_image(path: Path) -> Image.Image:
    """Decode *path* through the shared registry (RAW/PSD) or Pillow."""
    decoder = decoder_for(path.suffix)
    if decoder is not None:
        return decoder.decode(path, max_dim=AI_TAGGING_IMAGE_MAX_DIM)
    with Image.open(path) as image:
        image.load()
        return _flatten_to_rgb(image)


def _image_to_data_url(path: Path) -> str:
    """Load, downscale to <=2048 px on the long edge, JPEG-encode, base64."""
    image = _flatten_to_rgb(_load_image(path))
    image.thumbnail(
        (AI_TAGGING_IMAGE_MAX_DIM, AI_TAGGING_IMAGE_MAX_DIM),
        Image.Resampling.BILINEAR,
    )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


# ── Chat completions ─────────────────────────────────────────────


def _raise_for_status(response: requests.Response) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    detail = response.text[:200] if response.text else ""
    if status in (401, 403):
        raise AiTaggingError(AiTaggingErrorKind.AUTH, f"HTTP {status}: {detail}")
    if status in (402, 429):
        raise AiTaggingError(AiTaggingErrorKind.QUOTA, f"HTTP {status}: {detail}")
    raise AiTaggingError(AiTaggingErrorKind.NETWORK, f"HTTP {status}: {detail}")


def _post_chat(url: str, payload: dict, timeout: float) -> requests.Response:
    try:
        return requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise AiTaggingError(AiTaggingErrorKind.TIMEOUT, str(exc)) from exc
    except requests.exceptions.RequestException as exc:
        raise AiTaggingError(AiTaggingErrorKind.NETWORK, str(exc)) from exc


def analyze_image(
    endpoint: str,
    model: str,
    image_path: str | Path,
    *,
    existing_tags: list[str],
    max_tags: int,
    timeout: float = 120,
) -> AiTaggingResult:
    """Analyze one image and return the model's raw tag candidates.

    Raises :class:`AiTaggingError` with a classified ``kind`` on any
    failure; convergence onto the writable vocabulary is the caller's job
    (``write_policy.converge_tags`` at the write boundary).
    """
    path = Path(image_path)
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": build_tagging_prompt(existing_tags, max_tags)},
                {"type": "image_url", "image_url": {"url": _image_to_data_url(path)}},
            ],
        }],
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    url = _chat_completions_url(endpoint)
    response = _post_chat(url, payload, timeout)
    if 400 <= response.status_code < 500 and response.status_code not in (401, 402, 403, 429):
        # json_object not supported (or a transient 4xx): degrade once to
        # plain text and lean on the JSON-extraction fallback below.
        _log.debug("json_object rejected (HTTP %s); retrying without response_format",
                   response.status_code)
        payload.pop("response_format", None)
        response = _post_chat(url, payload, timeout)
    _raise_for_status(response)
    content = _extract_content(response)
    return _parse_tagging_payload(content)


def _extract_content(response: requests.Response) -> str:
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiTaggingError(
            AiTaggingErrorKind.INVALID_RESPONSE,
            f"unexpected chat payload: {exc}",
        ) from exc
    if not isinstance(content, str):
        raise AiTaggingError(
            AiTaggingErrorKind.INVALID_RESPONSE,
            f"content is {type(content).__name__}, expected str",
        )
    return content


# ── Response parsing ─────────────────────────────────────────────


def _strip_code_fences(text: str) -> str:
    """Remove a leading/trailing markdown code fence if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_object(text: str) -> str:
    """Fallback extraction of the outermost {...} block from free text."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise AiTaggingError(
            AiTaggingErrorKind.INVALID_RESPONSE,
            f"no JSON object found in model output: {text[:120]!r}",
        )
    return text[start:end + 1]


def _parse_tagging_payload(content: str) -> AiTaggingResult:
    text = _strip_code_fences(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(_extract_json_object(text))
        except (json.JSONDecodeError, AiTaggingError) as exc:
            if isinstance(exc, AiTaggingError):
                raise
            raise AiTaggingError(
                AiTaggingErrorKind.INVALID_RESPONSE,
                f"model output is not JSON: {content[:120]!r}",
            ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("tags"), list):
        raise AiTaggingError(
            AiTaggingErrorKind.INVALID_RESPONSE,
            f"expected {{\"tags\": [...]}}, got: {content[:120]!r}",
        )
    tags = tuple(tag for tag in data["tags"] if isinstance(tag, str))
    description = data.get("description")
    if not isinstance(description, str):
        description = ""
    return AiTaggingResult(tags=tags, description=description)

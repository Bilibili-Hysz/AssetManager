"""Shared asynchronous tasks for desktop sharing views."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal
from AssetsManager.domain.errors import ValidationError

_log = logging.getLogger(__name__)


class ShareApiResult(QObject):
    """Signal container retained by a request task until it completes."""

    finished = Signal(bool, object)


class ShareApiTask(QRunnable):
    """Run one local sharing API request without blocking the desktop UI."""

    def __init__(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        *,
        success_statuses: tuple[int, ...] = (200,),
    ) -> None:
        super().__init__()
        self._method = method
        self._url = url
        self._headers = headers or {}
        self._json_data = json_data
        self._success_statuses = success_statuses
        self.signals = ShareApiResult()

    def run(self) -> None:
        try:
            import requests

            response = requests.request(
                self._method,
                self._url,
                headers=self._headers,
                json=self._json_data,
                timeout=10,
            )
            payload = None
            if response.content:
                try:
                    payload = response.json()
                except ValueError:
                    # Non-JSON body: keep the status so callers can surface
                    # it instead of silently losing the response.
                    _log.warning(
                        "Share API %s %s returned non-JSON body (status %s)",
                        self._method, self._url, response.status_code,
                    )
                    self.signals.finished.emit(False, {"status": response.status_code, "error": "Invalid response"})
                    return
            self.signals.finished.emit(response.status_code in self._success_statuses, payload)
        except Exception:
            # Callers choose their localized user-facing error message. Do not
            # surface raw network or HTTP error strings in the UI.
            _log.warning("Share API request failed: %s %s", self._method, self._url, exc_info=True)
            self.signals.finished.emit(False, None)


class ShareCreationTask(QRunnable):
    """Create one share through the runtime service without blocking the UI."""

    def __init__(
        self,
        share_service: Any,
        paths: list[str],
        options: dict[str, Any] | None = None,
        base_url: str = "",
        requires_key: bool = False,
        *,
        session: Any = None,
        runtime: Any = None,
        generation: int | None = None,
    ) -> None:
        super().__init__()
        self._share_service = share_service
        self._session = session if session is not None else _service_session(share_service)
        self._runtime = runtime if runtime is not None else _service_runtime(share_service)
        self._runtime_epoch = _runtime_epoch(self._runtime, self._session, share_service)
        self._generation = generation
        self._paths = list(paths)
        self._options = dict(options or {})
        self._base_url = base_url.rstrip("/")
        self._requires_key = bool(requires_key)
        self.signals = ShareApiResult()

    def run(self) -> None:
        try:
            share = self._share_service.create_share(paths=self._paths, **self._options)
            if share is None:
                self.signals.finished.emit(False, {"error": "Failed to create share link"})
                return
            payload = share.to_public_dict()
            payload["url"] = f"{self._base_url}/s/{share.id}"
            payload["requires_key"] = self._requires_key
            self.signals.finished.emit(True, payload)
        except ValidationError as exc:
            self.signals.finished.emit(False, {"error": exc.message})
        except Exception:
            _log.exception("Share creation failed")
            self.signals.finished.emit(False, None)



def _service_session(service: Any) -> Any:
    """Return a service-bound session without requiring the new API shape."""
    values = vars(service) if hasattr(service, "__dict__") else {}
    if "_session" in values:
        return values["_session"]
    # Instance-level lookup: checking the class first can return a descriptor
    # (property/method) instead of the actual instance session.
    return getattr(service, "session", None)


def _service_runtime(service: Any) -> Any:
    """Return an optional runtime marker used by newer service adapters."""
    values = vars(service) if hasattr(service, "__dict__") else {}
    if "_runtime" in values:
        return values["_runtime"]
    return getattr(service, "runtime", None)


def _runtime_epoch(runtime: Any, session: Any, service: Any) -> Any:
    """Capture the strongest available lifecycle marker for a request."""
    if runtime is not None:
        epoch = getattr(runtime, "epoch", None)
        if epoch is not None:
            return epoch
    values = vars(service) if hasattr(service, "__dict__") else {}
    if "_runtime_epoch" in values:
        return values["_runtime_epoch"]
    return getattr(session, "event_token", None)

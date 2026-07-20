"""Shared asynchronous localhost API requests for desktop sharing views."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal


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
            payload = response.json() if response.content else None
            self.signals.finished.emit(response.status_code in self._success_statuses, payload)
        except Exception:
            # Callers choose their localized user-facing error message. Do not
            # surface raw network or HTTP error strings in the UI.
            self.signals.finished.emit(False, None)

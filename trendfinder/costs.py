"""Running total of OpenRouter spend for one browser session.

OpenRouter reports the cost of each request (`usage.cost`, in USD) for both Jev and
chat models. The Streamlit app keeps one `CostLog` per session and passes it to the
calls it makes, so the sidebar can show what the session has spent so far.
"""
from __future__ import annotations

import threading


class CostLog:
    """Thread-safe spend totals by kind ('jev', 'explain')."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usd: dict[str, float] = {}
        self._calls: dict[str, int] = {}

    def add(self, kind: str, usd) -> None:
        """Record one call. Ignores a missing or non-numeric cost."""
        if not isinstance(usd, (int, float)) or isinstance(usd, bool) or usd < 0:
            return
        with self._lock:
            self._usd[kind] = self._usd.get(kind, 0.0) + float(usd)
            self._calls[kind] = self._calls.get(kind, 0) + 1

    def usd(self, kind: str | None = None) -> float:
        with self._lock:
            return self._usd.get(kind, 0.0) if kind else sum(self._usd.values())

    def calls(self, kind: str | None = None) -> int:
        with self._lock:
            return self._calls.get(kind, 0) if kind else sum(self._calls.values())

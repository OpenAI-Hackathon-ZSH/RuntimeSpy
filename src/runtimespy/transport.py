"""Outbound event transport placeholders.

Implement these two functions later to POST payloads to the graph consumer.
RuntimeSpy deliberately keeps them as no-ops for now so instrumentation can be
integrated before the destination service and retry policy are decided.
"""

from __future__ import annotations

from typing import Any


def send_graph(payload: dict[str, Any]) -> None:
    """Send the zero-frequency graph when an instrumented service starts."""

    pass


def send_frequency(payload: dict[str, Any]) -> None:
    """Send node frequencies collected during one completed request."""

    pass

"""Automatic request-boundary integrations for supported web frameworks."""

from __future__ import annotations

from functools import wraps
from typing import Any


def install_optional_integrations() -> tuple[str, ...]:
    """Install the remote RuntimeSpy Flask integration when Flask is present."""
    try:
        from flask import Flask
    except ImportError:
        return ()
    original = Flask.wsgi_app
    if getattr(original, "__runtimespy_request_wrapper__", False):
        return ()

    @wraps(original)
    def wrapped(application: Any, environ: dict[str, Any], start_response: Any) -> Any:
        from .api import begin_request, end_request

        trace = begin_request()
        try:
            return original(application, environ, start_response)
        finally:
            end_request(trace)

    setattr(wrapped, "__runtimespy_request_wrapper__", True)
    Flask.wsgi_app = wrapped
    return ("flask",)

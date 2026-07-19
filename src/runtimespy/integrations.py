"""Automatic request-boundary integrations for supported web frameworks."""

from __future__ import annotations

from functools import wraps
from typing import Any


_FLASK_WRAPPER_MARKER = "__runtimespy_request_wrapper__"


def _instrument_flask_class(flask_class: type[Any]) -> bool:
    """Wrap ``Flask.wsgi_app`` once and return whether it was changed."""

    original = flask_class.wsgi_app
    if getattr(original, _FLASK_WRAPPER_MARKER, False):
        return False

    @wraps(original)
    def runtimespy_wsgi_app(
        application: Any,
        environ: dict[str, Any],
        start_response: Any,
    ) -> Any:
        # Import lazily to avoid an api -> integrations -> api cycle at startup.
        from .api import begin_request, end_request

        trace = begin_request()
        try:
            return original(application, environ, start_response)
        finally:
            end_request(trace)

    setattr(runtimespy_wsgi_app, _FLASK_WRAPPER_MARKER, True)
    flask_class.wsgi_app = runtimespy_wsgi_app
    return True


def install_optional_integrations() -> tuple[str, ...]:
    """Auto-install adapters for supported frameworks present in the process."""

    installed: list[str] = []
    try:
        from flask import Flask
    except ImportError:
        pass
    else:
        if _instrument_flask_class(Flask):
            installed.append("flask")
    return tuple(installed)

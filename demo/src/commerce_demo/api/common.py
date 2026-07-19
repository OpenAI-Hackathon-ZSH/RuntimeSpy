"""Request helpers shared by API blueprints."""

from __future__ import annotations

from typing import Any, cast

from flask import current_app, request

from ..container import CommerceContainer
from ..errors import ValidationError


def container() -> CommerceContainer:
    return cast(CommerceContainer, current_app.extensions["commerce_demo"])


def json_body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValidationError("request body must be a JSON object")
    return value


def request_role() -> str:
    return request.headers.get("X-Role", "customer").strip().lower()


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.remote_addr or "127.0.0.1"


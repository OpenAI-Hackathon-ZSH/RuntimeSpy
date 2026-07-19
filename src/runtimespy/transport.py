"""Best-effort HTTP transport for RuntimeSpy graph events."""

from __future__ import annotations

from http.client import HTTPException
import json
import logging
import sys
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


FULL_GRAPH_PATH = "/report/full_graph"
NODE_FREQUENCY_PATH = "/report/node"
REPORT_TIMEOUT_SECONDS = 5.0

logger = logging.getLogger(__name__)


def normalize_endpoint(endpoint: str | None) -> str | None:
    """Validate and normalize an optional HTTP reporting base URL."""

    if endpoint is None:
        return None
    normalized = endpoint.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        not normalized
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "RuntimeSpy endpoint must be an http(s) base URL without a query or fragment"
        )
    return normalized


def _post_json(endpoint: str | None, path: str, payload: dict[str, Any]) -> bool:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if endpoint is None:
        print(
            f"[RuntimeSpy report] HTTP disabled path={path} body={body}",
            file=sys.stderr,
            flush=True,
        )
        return False

    url = f"{endpoint}{path}"
    print(
        f"[RuntimeSpy report] POST {url} body={body}",
        file=sys.stderr,
        flush=True,
    )
    request = Request(
        url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=REPORT_TIMEOUT_SECONDS) as response:
            response.read()
    except (HTTPException, OSError, TimeoutError) as error:
        # Runtime instrumentation must never turn a successful application
        # request into a failure because the reporting service is unavailable.
        logger.warning("RuntimeSpy could not POST %s: %s", url, error)
        return False
    return True


def send_graph(
    payload: dict[str, Any], *, endpoint: str | None = None
) -> bool:
    """POST the startup zero-frequency graph to ``/report/full_graph``."""

    return _post_json(endpoint, FULL_GRAPH_PATH, payload)


def send_frequency(
    payload: dict[str, Any], *, endpoint: str | None = None
) -> bool:
    """POST one request's node counts to ``/report/node``."""

    return _post_json(endpoint, NODE_FREQUENCY_PATH, payload)

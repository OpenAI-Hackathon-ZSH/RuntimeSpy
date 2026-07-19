"""Flask application factory for the RuntimeSpy commerce demo."""

from __future__ import annotations

from typing import Any


def create_app(test_config: dict[str, Any] | None = None):
    from uuid import uuid4

    from flask import Flask, jsonify, request

    from .api import admin_api, catalog_api, order_api
    from .container import build_container
    from .errors import DomainError

    app = Flask(__name__)
    app.config.from_mapping(
        TESTING=False,
        MAINTENANCE_MODE=False,
        ALLOW_BACKORDERS=True,
        RISK_REVIEW_THRESHOLD=45,
        RISK_BLOCK_THRESHOLD=75,
        REFUND_WINDOW_DAYS=30,
    )
    if test_config:
        app.config.update(test_config)

    app.extensions["commerce_demo"] = build_container(app.config)
    app.register_blueprint(catalog_api)
    app.register_blueprint(order_api)
    app.register_blueprint(admin_api)

    @app.get("/health")
    def health():
        status = "maintenance" if app.config["MAINTENANCE_MODE"] else "ok"
        return jsonify({"status": status, "service": "commerce-demo"})

    @app.before_request
    def enforce_maintenance_mode():
        if not app.config["MAINTENANCE_MODE"]:
            return None
        if request.endpoint in {"health", "admin.set_maintenance"}:
            return None
        if request.headers.get("X-Role", "").lower() == "admin":
            return None
        return jsonify({"error": {"code": "maintenance", "message": "service unavailable"}}), 503

    @app.after_request
    def attach_response_metadata(response):
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", uuid4().hex)
        response.headers["X-Store-Revision"] = str(
            app.extensions["commerce_demo"].store.revision
        )
        return response

    @app.errorhandler(DomainError)
    def handle_domain_error(error: DomainError):
        return (
            jsonify(
                {
                    "error": {
                        "code": error.code,
                        "message": error.message,
                        "details": error.details,
                    }
                }
            ),
            error.status_code,
        )

    @app.errorhandler(404)
    def handle_not_found(_error):
        return jsonify({"error": {"code": "route_not_found", "message": "route not found"}}), 404

    @app.errorhandler(500)
    def handle_internal_error(error):
        if app.config["TESTING"]:
            raise error
        return jsonify({"error": {"code": "internal_error", "message": "unexpected error"}}), 500

    return app

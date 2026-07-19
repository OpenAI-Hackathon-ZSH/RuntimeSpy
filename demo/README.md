# RuntimeSpy Commerce Demo

This is a deliberately branch-rich Flask API for exercising RuntimeSpy against
something closer to a real service than a toy `hello world` application. It uses
an application factory, three Blueprints, an in-memory transactional store, and
separate pricing, inventory, risk, and order services.

The system models a small commerce and fulfillment platform with:

- catalog browsing and availability states;
- customer-tier, bulk, coupon, shipping, and tax pricing rules;
- inventory reservations, backorders, releases, and role-gated adjustments;
- explainable fraud scoring with approve, review, and block decisions;
- idempotent order creation, manual review, shipping, cancellation, and refunds;
- admin metrics, audit history, role checks, and maintenance mode.

Some rare/error branches are intentionally not exercised by the default traffic
script. This gives the exported graph a useful mixture of hot, cold, and unseen
logic for a frontend heatmap.

## Setup

The demo is configured as its own `uv` project. From this `demo` directory:

```bash
uv sync --extra test
```

`uv` reads `pyproject.toml`, creates `.venv`, and installs Flask and the test
dependencies. `app.py` loads RuntimeSpy and the demo package directly from this
checkout, so the command always exercises the current source files.

The equivalent `pip` setup is:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ..
python -m pip install -e ".[test]"
```

## 1. Start the demo server

```bash
uv run python app.py
```

The instrumented Flask server listens at `http://127.0.0.1:5000`. RuntimeSpy
starts before `commerce_demo` is imported and observes only `demo/src`.

Set a reporting endpoint when needed:

```bash
RUNTIMESPY_REPORT_ENDPOINT=http://127.0.0.1:9000 uv run python app.py
```

At startup RuntimeSpy POSTs the complete zero-frequency graph to
`$RUNTIMESPY_REPORT_ENDPOINT/report/full_graph`. Each completed HTTP request
POSTs that request's node counts to `$RUNTIMESPY_REPORT_ENDPOINT/report/node`.
Without this environment variable, HTTP reporting is disabled.

Choose a different server port with:

```bash
RUNTIMESPY_DEMO_PORT=5050 uv run python app.py
```

Swagger is available at
[`http://127.0.0.1:5000/docs/`](http://127.0.0.1:5000/docs/) and the raw spec at
[`http://127.0.0.1:5000/openapi.json`](http://127.0.0.1:5000/openapi.json).

## 2. Send simulated traffic

Keep the server running. In a second terminal, from the `demo` directory, run:

```bash
uv run python scripts/simulate_traffic.py --base-url http://127.0.0.1:5000
```

The traffic script only sends requests. It does not start or stop the server. It
covers successful, rejected, replayed, reviewed, shipped, refunded, cancelled,
administrative, and maintenance-mode paths.

The server stays alive after traffic completes, so the script can be run again
or requests can be sent manually through Swagger. Stop the server separately
with `Ctrl-C`; its exit handler refreshes `.runtimespy/export.json`.

The traffic process never initializes RuntimeSpy—the server process owns all
counters and the final export.

You can also request an on-demand snapshot while the server is still running:

```bash
cd demo
uv run runtimespy export
```

Example requests:

```bash
curl http://127.0.0.1:5000/api/v1/catalog/products

curl -X POST http://127.0.0.1:5000/api/v1/quotes \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"cust-vip","items":[{"sku":"HEADSET","quantity":2}],"coupon":"VIP20"}'

curl -X POST http://127.0.0.1:5000/api/v1/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: example-1' \
  -d '{"customer_id":"cust-standard","items":[{"sku":"MOUSE","quantity":2}]}'
```

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health and maintenance state |
| `GET` | `/docs/` | Interactive Swagger UI |
| `GET` | `/openapi.json` | OpenAPI 3.1 API description |
| `GET` | `/api/v1/catalog/products` | Filterable catalog list |
| `GET` | `/api/v1/catalog/products/<sku>` | Product and availability details |
| `POST` | `/api/v1/quotes` | Price items, discounts, delivery, and tax |
| `GET` | `/api/v1/inventory/<sku>` | Inventory state |
| `POST` | `/api/v1/inventory/<sku>/adjust` | Warehouse/admin stock adjustment |
| `POST` | `/api/v1/risk/evaluate` | Standalone explainable risk decision |
| `POST` | `/api/v1/orders` | Idempotent order creation |
| `GET` | `/api/v1/orders` | Filtered order list |
| `GET` | `/api/v1/orders/<id>` | Order details |
| `POST` | `/api/v1/orders/<id>/cancel` | State- and role-aware cancellation |
| `POST` | `/api/v1/orders/<id>/review` | Risk analyst approval/rejection |
| `POST` | `/api/v1/orders/<id>/ship` | Warehouse shipment transition |
| `POST` | `/api/v1/orders/<id>/refund` | Partial/full refund with approval rules |
| `GET` | `/api/v1/admin/metrics` | Operational summary |
| `GET` | `/api/v1/admin/audit` | Role-gated audit history |
| `POST` | `/api/v1/admin/maintenance` | Toggle maintenance mode |

Roles are supplied through the `X-Role` header. Useful demo roles are
`customer`, `support`, `support-lead`, `warehouse`, `risk-analyst`, `finance`,
`auditor`, and `admin`.

## Tests

```bash
uv run python -m unittest discover -s tests -q
```

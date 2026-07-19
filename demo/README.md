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

From this `demo` directory:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ..
python -m pip install -e ".[test]"
```

## Generate a graph without starting a server

```bash
python scripts/simulate_traffic.py
```

The script sends successful, rejected, replayed, reviewed, shipped, refunded,
cancelled, administrative, and maintenance-mode requests through Flask's test
client. It then stops RuntimeSpy explicitly and writes:

```text
demo/.runtimespy/export.json
```

That file can be given directly to the graph UI described in the repository's
main README.

## Run the API server

```bash
python app.py
```

RuntimeSpy starts before `commerce_demo` is imported, observes only `demo/src`,
and writes the final graph when the process exits. While it is running, request
an on-demand snapshot from another terminal:

```bash
cd demo
runtimespy export
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
python -m unittest discover -s tests -q
```


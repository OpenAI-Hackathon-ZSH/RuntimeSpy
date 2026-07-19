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
dependencies. The orchestration script adds the repository's `src` directory to
`PYTHONPATH`, so it always runs the local RuntimeSpy source.

The equivalent `pip` setup is:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ..
python -m pip install -e ".[test]"
```

## One command: server, traffic, graph

```bash
uv run python scripts/run_demo.py
```

`run_demo.py` performs the complete real-process flow:

1. chooses an available localhost port;
2. starts `app.py` as a separate instrumented Flask server process;
3. waits for `/health` to report ready;
4. sends real HTTP requests covering successful, rejected, replayed, reviewed,
   shipped, refunded, cancelled, administrative, and maintenance-mode paths;
5. sends `SIGINT` to stop the server cleanly;
6. waits for the server process's RuntimeSpy exit handler to overwrite:

```text
demo/.runtimespy/export.json
```

The script validates the new JSON and prints its node/edge summary. That file can
be given directly to the graph UI described in the repository's main README.

When the server starts, RuntimeSpy also calls the empty `send_graph` transport
hook with the complete zero-frequency graph. Each completed HTTP request calls
the empty `send_frequency` hook with only that request's node counts. RuntimeSpy
automatically wraps Flask when `init()` runs, so the demo application contains
no RuntimeSpy request hooks or middleware. Final process-wide JSON export
continues to happen normally when the server stops.

Choose a fixed port when needed:

```bash
uv run python scripts/run_demo.py --port 5050
```

## Open Swagger UI

Use `--swagger` to run the full traffic suite, open the interactive API docs in
your default browser, and keep the server alive while you try requests manually:

```bash
uv run python scripts/run_demo.py --swagger
```

The script prints and opens a URL such as:

```text
http://127.0.0.1:54321/docs/
```

Swagger UI is served locally by the Flask process. Its OpenAPI 3.1 document is
available at `/openapi.json`. The docs include request schemas, example values,
query/path/header parameters, role descriptions, and every demo endpoint. Press
Enter in the terminal when finished; the server exits and RuntimeSpy writes the
final graph JSON.

## Run server and traffic separately

Start the instrumented server in the first terminal:

```bash
uv run python app.py
```

With the default port, Swagger is available at
[`http://127.0.0.1:5000/docs/`](http://127.0.0.1:5000/docs/) and the raw spec at
[`http://127.0.0.1:5000/openapi.json`](http://127.0.0.1:5000/openapi.json).

RuntimeSpy starts before `commerce_demo` is imported, observes only `demo/src`,
and writes the final graph when the process exits. In a second terminal, send the
same real HTTP traffic suite:

```bash
cd demo
uv run python scripts/simulate_traffic.py --base-url http://127.0.0.1:5000
```

Stop the server with `Ctrl-C`; its exit handler refreshes
`.runtimespy/export.json`. The traffic process never initializes RuntimeSpy—the
server process owns all counters and the final export.

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

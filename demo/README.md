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

## Run the demo and traffic in two terminals

The server and traffic generator are independent processes. Open two terminals
in the `demo` directory; do not stop the server after starting it.

### Terminal 1: start the demo server

```bash
uv run python app.py
```

The instrumented Flask server listens at `http://127.0.0.1:8080`. RuntimeSpy
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
RUNTIMESPY_DEMO_PORT=8081 uv run python app.py
```

Swagger is available at
[`http://127.0.0.1:8080/docs/`](http://127.0.0.1:8080/docs/) and the raw spec at
[`http://127.0.0.1:8080/openapi.json`](http://127.0.0.1:8080/openapi.json).

### Terminal 2: send simulated traffic

To send traffic to the deployed demo, from the `demo` directory run:

```bash
uv run python scripts/simulate_traffic.py
```

Its default target is `http://34.239.92.98/`. To target the local server from
Terminal 1 instead, pass `--base-url http://127.0.0.1:8080`.

The traffic script only sends requests. It does not start or stop the server. It
covers successful, rejected, replayed, reviewed, shipped, refunded, cancelled,
administrative, and maintenance-mode paths. Requests are sent one at a time with
a two-second interval by default. Change the pacing with `--interval SECONDS`,
or use `--interval 0` to send them without a delay:

```bash
uv run python scripts/simulate_traffic.py \
  --base-url http://34.239.92.98/ \
  --interval 2
```

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
curl http://127.0.0.1:8080/api/v1/catalog/products

curl -X POST http://127.0.0.1:8080/api/v1/quotes \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"cust-vip","items":[{"sku":"HEADSET","quantity":2}],"coupon":"VIP20"}'

curl -X POST http://127.0.0.1:8080/api/v1/orders \
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

## Deploy to a public AWS EC2 instance

The repository includes a Python CDK stack in `infra/`. It builds
`demo/Dockerfile`, publishes the image to the CDK bootstrap ECR repository, and
runs it on an Amazon Linux 2023 `t3.micro` EC2 instance. The stack creates a
dedicated VPC with no NAT gateway, assigns a static Elastic IP, and maps public
port 80 to the container's port 8080. The security group allows public HTTP but
does not expose SSH.

The deployed service reports RuntimeSpy events to
`http://34.226.45.56:8000` by default, using `/report/full_graph` and
`/report/node`.

In the GitHub repository, open **Settings → Secrets and variables → Actions**
and create these repository secrets:

- `AWS_ACCESS_KEY_ID`
- `AWS_REGION`
- `AWS_SECRET_ACCESS_KEY`

The IAM principal behind those keys must be allowed to bootstrap and deploy CDK
stacks that use CloudFormation, EC2, VPC, ECR, S3, SSM, and IAM. For a disposable
hackathon account, `AdministratorAccess` is the simplest setup; for a shared or
production account, use a dedicated least-privilege deployment principal.

Optional configuration:

- `AWS_REGION` can alternatively be a repository variable. A secret takes
  precedence, and the default is `us-east-1`.
- Repository secret `RUNTIME_SPY_REPORT_ENDPOINT` overrides the default
  RuntimeSpy reporting service URL.

The **Deploy commerce demo** workflow runs automatically when relevant files
are pushed to `main`. It can also be started manually from the GitHub Actions
page. The workflow bootstraps the selected account/region, runs the demo tests,
builds the container, deploys the CDK stack, and waits for the public `/health`
endpoint. It writes the instance ID, public service URL, and Swagger URL to the
workflow summary.

To deploy the same stack locally:

```bash
python -m venv infra/.venv
source infra/.venv/bin/activate
python -m pip install -r infra/requirements.txt
npm install --global aws-cdk@2

account_id="$(aws sts get-caller-identity --query Account --output text)"
cdk bootstrap "aws://${account_id}/${AWS_REGION:-us-east-1}"
cdk deploy RuntimeSpyDemo --require-approval never
```

The EC2 instance, EBS volume, Elastic IP/public IPv4 address, and image storage
incur AWS charges while they exist. Remove the stack when it is no longer
needed:

```bash
cdk destroy RuntimeSpyDemo
```

## Tests

```bash
uv run python -m unittest discover -s tests -q
```

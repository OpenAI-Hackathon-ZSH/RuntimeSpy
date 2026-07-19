# RuntimeSpy - Quick Start Guide

Real-time code instrumentation that tracks execution frequencies at every code location.

## What It Does

RuntimeSpy captures which code paths execute and how often by installing checkpoints at runtime. It's designed to integrate with any Python application and report execution data to a backend service.

## Prerequisites

- Python 3.12+ (requires CPython `sys.monitoring`)
- FastAPI backend running (see backend setup)

## Quick Start

### 1. Start the Backend API

```bash
cd /path/to/Code-Manager
venv/bin/python services/backend/server.py
```

The backend will start on `http://localhost:8000` and provide:
- `POST /report/full_graph` - receive initial graph with all frequencies = 0
- `POST /report/node` - receive frequency updates from instrumented code
- `GET /api/stats` - frontend polling endpoint for real-time data

### 2. Start the Instrumented Mock Service

```bash
CODE_MANAGER_INSTRUMENT=1 \
CODE_MANAGER_BACKEND_URL=http://127.0.0.1:8000 \
venv/bin/uvicorn services.mock.server:app --host 127.0.0.1 --port 8100
```

**Environment variables:**
- `CODE_MANAGER_INSTRUMENT=1` - Enable RuntimeSpy instrumentation
- `CODE_MANAGER_BACKEND_URL` - Where to send instrumentation data

The mock service will:
- Initialize RuntimeSpy on startup
- Send the full graph (750 nodes, 799 edges) to backend's `/report/full_graph`
- Accept HTTP requests on `http://localhost:8100/orders`
- Send frequency updates to backend's `/report/node` after each request

### 3. Run the Workload

```bash
cd /path/to/Code-Manager
venv/bin/python run_mock_workload.py --script representative --repeat --interval 2
```

This sends HTTP requests to the mock service:
- `--script representative` - Use realistic customer segments and order types
- `--repeat` - Keep running indefinitely
- `--interval 2` - Send a request every 2 seconds

### 4. View Live Updates in Frontend

Open `http://localhost:3000` in your browser and click **"Live Backend"**

The visualization updates every 3 seconds showing:
- Nodes growing (size = execution frequency)
- Nodes brightening (opacity = execution frequency)
- Edges thickening (thickness = execution frequency)
- Summary stats updating (executed nodes, unseen nodes, coverage %)

## Data Flow

```
Workload (sends HTTP requests)
    ↓
Mock Service (instrumented with RuntimeSpy)
    ├→ Startup: POST /report/full_graph (750 nodes)
    ├→ Per request: POST /report/node (batch frequency updates)
    ↓
Backend (caches graph + accumulates frequencies)
    ├→ In-memory: graph_cache
    ├→ On disk: .graph_cache.json
    ↓
Frontend (polls for updates)
    └→ GET /api/stats every 3 seconds
        └→ React re-renders with updated node frequencies
```

## What's Instrumented

**Core functions** (always execute):
- `validate_order()` - order validation
- `check_inventory()` - inventory check
- `calculate_order_total()` - pricing calculation
- `process_payment()` - payment processing
- `create_shipment()` - shipment creation
- `send_order_confirmation()` - confirmation email

**Feature-gated functions** (execute based on customer segment):
- `apply_loyalty_points()` - Premium tier only
- `apply_vip_pricing()` - Premium tier only
- `ai_recommendations()` - Early adopters only
- `sms_notification()` - Non-EU regions only
- `international_shipping()` - Variable by region/tier

**Dead code** (never executed, frequency = 0):
- `legacy_payment_gateway()` - deprecated
- `bitcoin_payment()` - never implemented
- `old_inventory_sync()` - obsolete
- `calculate_tax_by_zipcode()` - replaced

## Stopping the System

Press `Ctrl+C` in each terminal.

Backend saves final state to `.graph_cache.json` for persistence.

## Troubleshooting

**"RuntimeSpy requires CPython 3.12 or newer"**
- Check Python version: `python --version`
- Must be 3.12+, using PyPy/Conda other implementations won't work

**Backend not receiving updates**
- Verify `CODE_MANAGER_BACKEND_URL` is set correctly
- Check backend is running: `curl http://localhost:8000/health`
- Check logs in mock service terminal

**Frontend shows 0 nodes**
- Ensure workload is running (sending requests)
- Wait for at least one poll cycle (3 seconds)
- Check browser console for fetch errors

**Need fresh start**
- Kill all three services with `Ctrl+C`
- Run: `curl -X POST http://localhost:8000/clear`
- Restart all services

## Configuration

Mock service environment variables:
- `CODE_MANAGER_INSTRUMENT` - Set to `1` to enable RuntimeSpy
- `CODE_MANAGER_BACKEND_URL` - Backend endpoint (default: `http://127.0.0.1:8000`)

Backend options:
- Runs on port `8000` (configurable in code)
- Stores cache in `.graph_cache.json` in project root

Workload script options:
- `--script` - `representative` (realistic), `simple` (minimal)
- `--repeat` - Run indefinitely
- `--interval N` - Seconds between requests

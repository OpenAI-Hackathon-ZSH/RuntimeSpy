# RuntimeSpy

RuntimeSpy gives AI coding agents runtime evidence for finding and removing
unused Python logic. It records how often every logical control-flow node in a
selected source tree executes, then exports the project as a graph that an agent
or visualization tool can inspect.

## Built with Codex & GPT-5.6

We used **Codex and GPT-5.6** to build **RuntimE.Razor** across three separate
codebases, running three Codex sessions in parallel so we could develop them
simultaneously.

For lightweight tasks such as UI updates and copy changes, we used GPT-5.6 in
light mode for fast iteration. For complex work, including AST instrumentation
and system-wide refactoring, we used Codex-5.6 advanced mode, which could reason
deeply and complete difficult tasks with high accuracy.

https://github.com/user-attachments/assets/9552ec28-fdc6-4dcc-8aa9-371020e36850

## Why RuntimeSpy

AI coding agents are good at adding code, but much less certain about removing
it:

1. Static analysis alone cannot resolve every dynamic Python behavior, so an
   agent often cannot confidently decide whether a function, branch, or handler
   is truly unused.
2. Coding agents tend to overbuild. Defensive branches, speculative
   abstractions, and never-used features accumulate because adding code feels
   safer than deleting it.
3. Every unnecessary line makes the repository harder to understand and costs
   future agents more context tokens to read, reason about, and modify.

RuntimeSpy adds the missing runtime signal. For the workloads you observe, it
reports exact execution counts for functions, branches, loops, handlers, and
basic blocks. A coding agent can combine this graph with tests, static analysis,
and product knowledge to identify deletion candidates, verify them, and remove
them with much higher confidence.

The result is a smaller, simpler repository with less maintenance overhead and
lower token cost for future AI-assisted development. RuntimeSpy only observes
source roots selected by the user, so dependencies, the standard library, and
unrelated packages stay out of the graph.

> RuntimeSpy reports code that was **not observed** during recorded runs. A zero
> count is exact for those runs, but it is evidence of missing runtime coverage,
> not universal proof that the code is dead. Use representative workloads before
> deleting code.

## Branch-rich Flask demo

[`demo/`](demo/) contains a realistic in-memory commerce API with catalog,
pricing, inventory, risk, order, fulfillment, refund, and administration flows.
The server and traffic generator run as two independent commands, so traffic can
be replayed without restarting the instrumented service. See
[`demo/README.md`](demo/README.md) for local usage and public AWS EC2 deployment.

## Requirements

- CPython 3.12 or newer
- No runtime dependencies

## Install for development

```bash
python -m pip install -e .
```

## Quick start: embedded probe

Install RuntimeSpy in the target project's environment, then initialize it at
the very beginning of the application's entry point:

```python
import runtimespy

runtimespy.init(
    source=["src"],
    endpoint="https://runtime.example/api",
    skip_modules=[
        "my_app.generated",
        "my_app.generated.*",
    ],
)

from my_app import main

main()
```

`init()` installs the monitor in the current process. Every subsequent line in
the selected source roots is counted, and results are written automatically when
the process exits. `endpoint` is optional; without it HTTP reporting is disabled.
RuntimeSpy does not rewrite target `.py` files and does not write periodic
snapshots.

From another terminal, request the current counters at any time:

```bash
# Ask the running process for its current counters and update one JSON file
runtimespy export

# Choose a different output file
runtimespy export --output runtime.json

# Print JSON to stdout instead of writing a file
runtimespy export --output -
```

The command contacts the active RuntimeSpy process through a local on-demand
endpoint and atomically overwrites `.runtimespy/export.json`. When the process
exits, RuntimeSpy writes the final counters to the same file automatically. The
exporter falls back to SQLite when no process is active. Only one default JSON
file is maintained.

## Startup and per-request events

When `endpoint` is configured, RuntimeSpy reports two types of events:

1. `init()` immediately builds the complete project graph with every node and
   edge `frequency` set to `0`, then POSTs it to
   `{endpoint}/report/full_graph`.
2. `init()` automatically detects Flask and wraps its WSGI request boundary.
   Before application handling RuntimeSpy starts a request-local counter; after
   the request returns or raises, it calls
   `{endpoint}/report/node` with only the nodes entered by that request. The
   target Flask application does not need hooks or middleware.

Both requests use `POST` with `Content-Type: application/json`. Reporting is
best-effort with a five-second timeout: a network or reporting-service failure
is logged but never fails the instrumented application request. Authentication,
retry, and buffering are not implemented yet. Before every POST, RuntimeSpy logs
the destination URL and the complete JSON request body to stderr. When HTTP
reporting is disabled, RuntimeSpy still prints every generated report body with
an `HTTP disabled` marker.

The per-request payload has this exact shape:

```json
{
  "Frequency": [
    {"node": "node_a74bdb17f4db2c34bcc1", "count": 3},
    {"node": "node_8496c50571534d18046b", "count": 1}
  ]
}
```

See
[`examples/request-frequency.example.json`](examples/request-frequency.example.json)
for a standalone fixture. Counts are local to one request, never cumulative.
RuntimeSpy stores them in a Python `ContextVar`, so overlapping threads or async
request contexts do not use a shared before/after snapshot.

The Flask adapter is installed automatically by `runtimespy.init()`. Other
framework adapters can define their request boundary with the public
`runtimespy.begin_request()` and `runtimespy.end_request(trace)` APIs; calling
them without an active RuntimeSpy session is a safe no-op.

## JSON graph data contract

The complete, frontend-ready sample is
[`examples/runtime-export.example.json`](examples/runtime-export.example.json).
It is a valid `final` export with every field included, not an abbreviated
snippet. The sample models this source:

```python
def choose_plan(user):
    if user.is_suspended:
        return "blocked"
    if user.is_premium:
        return "pro"
    else:
        return "free"

selected = choose_plan(current_user)
```

In the simulated run, `choose_plan` was called 100 times. The suspended branch
was never entered, while the premium split was taken 72 times and the free split
28 times. The sample therefore contains both hot nodes and two zero-frequency
nodes that a UI can highlight as unobserved logic.

### Top-level export

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of the entire export envelope. Currently `2`. |
| `generated_at` | string | UTC ISO 8601 time at which this snapshot was created. |
| `mode` | string | `initial`, `live`, `final`, or `stored`; see the mode table below. |
| `project.roots` | string[] | Absolute project roots that contributed data. |
| `summary` | object | Convenience copy of `graph.summary` for dashboards. |
| `graph` | object | The control-flow graph and its file/scope hierarchy. |
| `active_sessions` | object[] | Present in `live` mode. Describes every process merged into the snapshot. |
| `session` | object | Present in `initial` and `final` modes. Describes the instrumented process. |
| `latest_run` | object or null | Present in `stored` mode. Metadata for the newest persisted run. |

Mode changes metadata and the counter window, but not the graph shape:

| Mode | Produced when | Frequency window |
| --- | --- | --- |
| `initial` | `init()` POSTs to `{endpoint}/report/full_graph` when reporting is enabled | Zeroed topology; every node and edge frequency is `0`. |
| `live` | `runtimespy export` reaches one or more running processes | Current sessions; matching node and edge counts are summed across processes. |
| `final` | An instrumented process exits or its session is stopped | The just-completed process session. |
| `stored` | No live process is available and the CLI reads SQLite | Cumulative data retained from completed runs. |

### `graph`

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of the nested graph contract. Currently `1`. |
| `type` | string | Currently always `control_flow`. |
| `summary.nodes` | integer | Total number of logical nodes. |
| `summary.edges` | integer | Total number of graph edges. |
| `summary.executed_nodes` | integer | Nodes whose `frequency` is greater than zero. |
| `summary.unseen_nodes` | integer | Nodes whose `frequency` is zero. |
| `hierarchy.files` | object[] | File index used for grouping and navigation. |
| `nodes` | object[] | Flat node list. Use `id` as the primary key. |
| `edges` | object[] | Flat directed edge list. `from` and `to` reference node IDs. |

Each item in `hierarchy.files` has:

| Field | Meaning |
| --- | --- |
| `path` | Project-relative source path; it matches `node.path`. |
| `module` | Importable Python module name when one can be determined. |
| `root_node_id` | The file's `module_entry` node. It can be `null` if the file could not be parsed. |
| `node_ids` | IDs of every node belonging to this file. |
| `scopes` | Lightweight index of module and function entry nodes. Classes and constructors are structural and are not coverage nodes. |

### Node contract

Every item in `graph.nodes` contains all of these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable ID prefixed with `node_`. Use it as the render key. |
| `type` | string | Logical role, such as `condition`, `branch_true`, or `basic_block`. |
| `label` | string | Short display label generated from the source construct. |
| `path` | string | Project-relative source file path. |
| `module` | string | Python module containing the node. |
| `qualname` | string | Owning function/class qualified name, or `<module>`. |
| `parent_id` | string or null | Logical containment parent, not necessarily the previous execution node. |
| `start_line` | integer | One-based first source line. |
| `start_column` | integer | Zero-based first UTF-8 byte column. |
| `end_line` | integer | One-based last source line. |
| `end_column` | integer | Zero-based, exclusive ending UTF-8 byte column. |
| `entry_line` | integer | Line whose runtime event supplies this node's counter. |
| `frequency` | integer | Number of times the logical node was entered in the export's frequency window. |

Node IDs are derived from the source path, source-content hash, qualified name,
node type, label, and location. They remain stable across exports of unchanged
source. Editing that source intentionally produces new IDs, which prevents a UI
from silently joining counters from different code versions.

Ranges may overlap. For example, a `branch_true` wrapper and the `basic_block`
inside it can point at the same source lines. They represent different graph
semantics and must not be deduplicated by location.

Supported node types are grouped below:

| Category | Node types |
| --- | --- |
| Scope and structure | `module_entry`, `function_entry`, `basic_block` |
| Conditionals | `condition`, `branch_true`, `branch_false` |
| Loops | `for_iteration`, `while_condition`, `loop_body`, `loop_else`, `loop_exit` |
| Exceptions | `try_body`, `except_handler`, `try_else`, `finally_block` |
| Pattern matching | `match_subject`, `match_case`, `match_unmatched` |
| Context managers | `with_context` |

A `basic_block` is one or more consecutive non-control statements. Its label is
made from AST statement names such as `Assign`, `Expr`, `Return`, or `Raise`.

### Edge contract

Every item in `graph.edges` contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable edge ID prefixed with `edge_`. |
| `from` | string | Source node ID. |
| `to` | string | Destination node ID. |
| `type` | string | Control-flow or structural relationship. |
| `frequency` | integer | Traversal count when measurable; otherwise `0`. RuntimeSpy never emits `null` here. |

| Edge type | Meaning |
| --- | --- |
| `entry` | Enter the first child node of a module, function, branch, or region. |
| `next` | Continue sequentially to the next logical node. |
| `true`, `false` | Select an `if` outcome. |
| `iterate`, `loop_back`, `exit` | Enter a loop body, repeat it, or leave the loop. |
| `exception`, `normal`, `finally` | Exception handler, normal `try` completion, or finalization path. |
| `case`, `unmatched` | Select a `match` case or take no case. |

RuntimeSpy emits `0` instead of `null` for edges without a reliable traversal
counter. For measured control edges (`true`, `false`, `iterate`, `exit`,
`exception`, `case`, and `unmatched`), zero means that the path was not observed.
For structural edges such as `entry`, `next`, `loop_back`, `normal`,
and `finally`, zero only means “no edge-level counter”; the edge still defines
the graph topology.

### Frequency and UI guidance

`frequency` is a count, not elapsed time or CPU cost. It answers “how many times
did this logic start?” A zero is evidence of missing runtime coverage, not proof
that the code is dead; environment-specific and rare paths may simply be absent
from the recorded workload.

For a graph UI, a practical ingestion and display strategy is:

1. Index `graph.nodes` by `id`, then resolve every edge through `from` and `to`.
2. Use `hierarchy.files` for the file tree and `scopes` for function drill-down.
3. Use control-flow `edges` for layout; use `parent_id` only for containment or collapsing groups.
4. Color nodes by `frequency`. A `log1p(frequency)` scale works better than a linear scale when hot loops dominate the counts.
5. Render `frequency === 0` as “unobserved” with a distinct neutral or warning treatment, not as confirmed dead code.
6. Scale measured control-edge width by `frequency`; render structural edge types with a thin or dashed style.
7. For measured sibling edges, show ratios such as `72 / (72 + 28) = 72%` to explain branch behavior.
8. Open the source viewer using `path` and the start/end coordinates when a node is selected.

The graph recognizes module and function entry, basic blocks, `if/elif/else`
branches, `for/while` loops, `try/except/else/finally`, `match/case`, `with`,
returns, raises, breaks, and continues. Class and definition syntax are
structural metadata, and constructor entry points are lifecycle plumbing, so
they are intentionally not emitted as coverage nodes. Logic within a constructor
(for example, an `if` branch) remains in the graph. Package `__init__.py` files
are also excluded, avoiding import-only nodes in the graph.

For a precise collection window, stop it explicitly:

```python
session = runtimespy.init(source="src")
run_application()
session.stop()
```

## Optional CLI workflow

Projects that do not want to add an import can use the CLI wrapper instead:

```bash
runtimespy init
runtimespy inspect
runtimespy run -- python app.py
runtimespy run -- python -m my_app
runtimespy run --context unit-tests -- pytest -q
pytest --runtimespy --runtimespy-context unit-tests
```

RuntimeSpy stores cumulative counters in `.runtimespy/runtime.db`. If a source
file changes, counters for that file are reset so old line numbers are not mixed
with the new source. The latest requested or completed snapshot is stored in
`.runtimespy/export.json`.

## Configuration

The CLI command `runtimespy init` only detects likely source roots and writes
`.runtimespy.toml`; it is optional when parameters are passed directly to the
Python `init()` function:

```toml
[runtimespy]
source = ["src"]
include_modules = ["my_app", "my_app.*"]
exclude_modules = ["my_app.generated", "my_app.generated.*"]
exclude_paths = ["**/generated/**", "**/vendor/**"]
data_file = ".runtimespy/runtime.db"
```

The same keys can instead be placed under `[tool.runtimespy]` in
`pyproject.toml`. When both exist, `.runtimespy.toml` wins.

Filtering follows these rules:

1. A file must resolve inside one of the configured source roots.
2. If `include_modules` is non-empty, a module must match an include rule.
3. Module and path excludes are applied last and always win.
4. Virtual environments, caches, VCS metadata, and site-packages are skipped by
   default.

A module rule without wildcards includes its descendants. For example,
`skip_modules=["my_app.generated"]` skips both that module and
`my_app.generated.client`. Wildcard rules use shell-style matching.

Use `runtimespy inspect --show-skipped` to preview the exact file set before a
run, or `runtimespy explain path/to/file.py` to see why one file is included or
excluded.

## Commands

```text
runtimespy init       Create project configuration
runtimespy inspect    Preview included and excluded Python files
runtimespy explain    Explain the decision for one source file or module
runtimespy run        Record a Python script, module, or pytest run
runtimespy export     Export live or stored counters as JSON
```

RuntimeSpy deliberately executes Python targets in the current process so the
monitor can observe them. Automatic propagation into subprocesses,
`multiprocessing`, pytest-xdist, Celery, and Gunicorn workers is planned but is
not part of the first release.

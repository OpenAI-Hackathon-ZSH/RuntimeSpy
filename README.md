# RuntimeSpy

RuntimeSpy records how often logical control-flow nodes in a Python project
execute and exports the project as a graph. It only observes source roots
selected by the user, so dependencies, the standard library, and unrelated
packages stay out of the report.

> RuntimeSpy reports code that was **not observed** during recorded runs. A zero
> count is evidence of missing runtime coverage, not proof that code is dead.

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
    skip_modules=[
        "my_app.generated",
        "my_app.generated.*",
    ],
    report=True,
)

from my_app import main

main()
```

`init()` installs the monitor in the current process. Every subsequent line in
the selected source roots is counted, and results are written automatically when
the process exits. It does not rewrite target `.py` files and does not write
periodic snapshots.

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

The JSON has a stable top-level shape:

```json
{
  "schema_version": 2,
  "mode": "live",
  "project": {"roots": ["/path/to/project"]},
  "active_sessions": [],
  "summary": {
    "nodes": 42,
    "edges": 51,
    "executed_nodes": 35,
    "unseen_nodes": 7
  },
  "graph": {
    "type": "control_flow",
    "nodes": [
      {
        "id": "node_8f4a...",
        "type": "branch_true",
        "path": "src/my_app/service.py",
        "start_line": 12,
        "start_column": 8,
        "end_line": 14,
        "end_column": 24,
        "frequency": 1200
      }
    ],
    "edges": [
      {
        "from": "node_condition",
        "to": "node_8f4a...",
        "type": "true",
        "frequency": 1200
      }
    ]
  }
}
```

Every graph node contains a stable ID, node type, source path, start/end line and
column, owning qualified name, parent node, and `frequency`. Frequency means the
number of times the logical node was entered since the current RuntimeSpy
session started. A source-content change produces new node IDs so counters from
different code versions cannot be confused.

`live` and `final` frequencies belong to the current process session and start
at zero when `runtimespy.init()` runs. A later `stored` export represents the
cumulative runs retained in the SQLite database.

The first graph version recognizes module and function entry, basic blocks,
`if/elif/else` branches, `for/while` loops, `try/except/else/finally`,
`match/case`, `with`, definitions, returns, raises, breaks, and continues.
Control-flow edges represent sequential execution, true/false selection, loop
iteration and exit, exception paths, scope entry, and definition relationships.

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
runtimespy report --open
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
runtimespy report     Generate a self-contained HTML heatmap
runtimespy export     Export live or stored counters as JSON
```

RuntimeSpy deliberately executes Python targets in the current process so the
monitor can observe them. Automatic propagation into subprocesses,
`multiprocessing`, pytest-xdist, Celery, and Gunicorn workers is planned but is
not part of the first release.

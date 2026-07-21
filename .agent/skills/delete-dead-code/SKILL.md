---
name: delete-dead-code
description: Generate GitHub pull requests that remove all Python code with zero frequency (frequency=0) from RuntimeSpy instrumentation reports. Trust the runtime evidence completely.
---

# Remove dead code paths

Delete code marked as unobserved (frequency=0) by RuntimeSpy. Nodes with frequency=0 
were never executed during the capture window and are safe to remove.

**Trust the report.** The instrumentation data is the source of truth. If you provide 
representative traffic data, frequency=0 means the code is truly unreachable.

## Inputs

Choose exactly one source of runtime evidence:

```bash
# Cloud RuntimeSpy backend (default)
curl --fail --silent --show-error http://34.226.45.56:8000/stats/clean

# Local RuntimeSpy backend
curl --fail --silent --show-error http://localhost:8000/stats/clean

# An exported instrumentation report
instrumentation-report.json
```

The report contains `graph.nodes[]` with `frequency` counts. Nodes with `frequency: 0` 
are deletion candidates.

## Workflow

1. Load the instrumentation report (from backend or file).
2. Identify all nodes with `frequency: 0` across all files.
4. Group candidates for deletion:
   - **`--single-pr`**: All nodes in one PR (recommended)
   - **`--max-prs N`**: Up to N PRs, one per file
   - **`--limit N`**: Legacy mode, top N files
5. Apply all deletions directly to source files. Remove:
   - Function/class definitions with frequency=0
   - Module-level statements with frequency=0
   - Import statements if they become orphaned
6. Commit changes with a clear message referencing the instrumentation data.
7. Push branch and create a GitHub PR.
8. If authentication fails, report the error and stop.

## When to run

Run this skill when you have a production traffic instrumentation report. The workflow 
fetches the latest report from the RuntimeSpy backend and creates a PR with deletions.

Ensure your report captures:
- Real production traffic (users, API clients, batch jobs)
- Diverse traffic patterns over time
- NOT unit/integration test suites (those don't reflect production use)

## How it works

Invoking this skill triggers the GitHub Actions workflow `dead-code-cleanup.yml`, which:
1. Fetches the latest report from the RuntimeSpy backend
2. Analyzes dead code (frequency=0 nodes)
3. Creates a PR with deletions

The workflow runs in GitHub Actions with automatic credentials, so no local auth issues.

## Invocation

```bash
# The skill automatically runs:
gh workflow run dead-code-cleanup.yml

# Or manually from the command line:
gh workflow run dead-code-cleanup.yml
```

## Report format

The instrumentation report must include:
- `summary.nodes` — total code paths in graph
- `summary.executed_nodes` — count of exercised code paths
- `graph.nodes[]` — array with `{path, frequency, start_line, end_line, ...}`

Nodes with `frequency: 0` will be analyzed for deletion.

## Output

The skill generates a single PR containing:
- All deletions from frequency=0 nodes
- Clean commit message with analysis summary
- Easy to review and revert if needed

## Trust model

- **Trust runtime frequency data only.** If frequency=0, the code was never executed 
  during production traffic. That is the source of truth.
- **Ignore unit tests.** Tests are not a validation gate. Code can be tested but unused 
  in production. If frequency=0, it's dead—delete it.
- **Your responsibility:** Provide representative runtime data. Run the server with 
  real production traffic (not just test suites). The report quality depends on 
  traffic volume and diversity, not test coverage.
- **Reviewer role:** The PR review catches missed dependencies or unexpected deletions 
  based on production knowledge, not test suites.
- **Easy rollback:** If a deletion was wrong, simply revert the PR.

**Goal:** Remove production-dead code. frequency=0 = not reached by real users/traffic. 
Delete it, regardless of test coverage.

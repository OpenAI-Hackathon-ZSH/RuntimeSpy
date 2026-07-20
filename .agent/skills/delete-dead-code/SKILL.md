---
name: delete-dead-code
description: Generate reviewable GitHub pull requests that remove Python code unobserved by RuntimeSpy. Runtime evidence may come from the cloud RuntimeSpy backend, a local backend, or an export JSON file.
---

# Generate dead-code cleanup PRs

Use RuntimeSpy only as evidence. Do **not** call a backend cleanup endpoint:
the agent performs the analysis, edits, verification, branch creation, and PR
creation locally. A zero-frequency node means unobserved in a traffic window,
not proven dead code.

## Inputs

Choose exactly one source of runtime evidence:

```bash
# Cloud RuntimeSpy backend (default)
curl --fail --silent --show-error http://34.226.45.56:8000/stats/clean

# Local RuntimeSpy backend
curl --fail --silent --show-error http://localhost:8000/stats/clean

# An exported graph supplied by the user
<instrumentation.json>
```

The graph is an export envelope. Candidates are `graph.nodes` with
`frequency: 0`; they identify source through fields such as `path`,
`start_line`, `end_line`, `type`, `label`, and `qualname`.

## Workflow

When asked to run this skill with `--limit N`:

1. Load the selected runtime evidence and list the zero-frequency candidates.
   Fetch the cloud source only when no local URL or file was provided.
2. Group candidates into the smallest coherent deletion units. Respect
   `--limit N` as the maximum number of PRs, not a promise to create unsafe
   PRs.
3. Inspect each current source location; the graph's line numbers may be stale.
   Use static searches to check callers, imports, Flask blueprint registration,
   OpenAPI declarations, tests, scripts, configuration, examples, and docs.
4. Only select a group when runtime evidence and static analysis both support
   removal. Never remove startup/infrastructure code, security or error paths,
   public API contracts, or reachable code merely because one branch was
   unobserved.
5. For every selected group, make the complete local cleanup: implementation,
   orphaned imports, registrations, tests solely for the removed feature, and
   stale documentation. Do not leave broken imports or route declarations.
6. Run the relevant tests and a syntax check. For the demo prefer:

   ```bash
   PYTHONPATH=demo/src demo/.venv/bin/python -m unittest discover -s demo/tests -v
   ```

7. Create one focused branch, commit, push, and GitHub PR per safe group using
   `gh`. The PR body must state the RuntimeSpy nodes, static-reference checks,
   test results, confidence, and remaining risk. If GitHub authentication is
   unavailable, complete the analysis and local patch but stop before pushing
   and clearly report the required `gh auth login` action.

## Invocation examples

```text
delete-dead-code --limit 2
delete-dead-code --source http://localhost:8000 --limit 1
delete-dead-code instrumentation.json --limit 3
```

## Safety requirements

- Do not create a PR from zero-frequency evidence alone.
- Prefer no PR to an uncertain deletion.
- Keep each PR independent, small, and easy to revert.
- Never modify the RuntimeSpy reporting service or its endpoint as part of a
  cleanup.

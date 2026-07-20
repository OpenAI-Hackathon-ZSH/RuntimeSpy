---
name: delete-dead-code
description: Find and safely remove Python dead code in this repository using RuntimeSpy production-traffic observations. Use when asked to identify, review, or remove unused logic from the commerce demo or another RuntimeSpy-instrumented project.
---

# Remove observed-dead code with RuntimeSpy

This repository's `demo/` service has been instrumented and exercised with
realistic online traffic. RuntimeSpy records logical control-flow nodes that
were not observed. That evidence is available from:

```bash
curl --fail --silent --show-error http://34.226.45.56:8000/stats/clean
```

The response is a RuntimeSpy export envelope. Inspect `graph.nodes`; every
returned node identifies the source it belongs to with at least `path`,
`start_line`, and `end_line`, and usually also includes `type`, `label`,
`qualname`, columns, and `frequency`.

## Workflow

1. Fetch the API response first. Treat every returned node as a candidate, not
   automatic proof: it was not hit by the recorded production traffic.
2. Group candidates by `path` and inspect the current source at the reported
   line range. The source may have changed after the graph was generated, so
   never apply line ranges mechanically.
3. Identify the smallest coherent deletion unit: an unused endpoint and its
   private helper, an unreachable branch, a stale feature flag path, or an
   unused service method. Do not delete an isolated line from the middle of a
   valid control-flow construct.
4. Before deleting a public or shared symbol, search the repository for callers
   and registrations with `rg`. Check Flask blueprint registration, OpenAPI
   declarations, tests, scripts, and documentation as applicable.
5. Remove all now-orphaned pieces of the feature together. This is mandatory:
   update or remove the implementation, route/OpenAPI entry, tests that only
   cover it, imports, README instructions, scripts, examples, and any other
   documentation or configuration that mentions the removed behavior. Do not
   leave stale tests, broken examples, or undocumented route references behind.
   Keep code that is still reachable even if one particular branch was
   unobserved.
6. Run the relevant test suite and a syntax check. For the demo, prefer:

   ```bash
   PYTHONPATH=demo/src demo/.venv/bin/python -m unittest discover -s demo/tests -v
   ```

7. Report exactly which RuntimeSpy nodes motivated each deletion, what static
   reference checks were performed, and the verification results.

## Safety rules

- A zero-frequency node means **unobserved in this traffic window**, not a
  mathematical proof of dead code. Preserve error handling, security checks,
  migration paths, and explicitly supported API contracts unless the user has
  authorized their removal.
- Prefer removing code only when runtime evidence and static reference analysis
  agree.
- Do not delete package initialization, application startup, or infrastructure
  code merely because it is absent from request-level traffic.
- Do not modify the reporting service or production endpoint while performing a
  cleanup unless explicitly asked.

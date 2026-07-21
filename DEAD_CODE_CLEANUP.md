# Dead Code Cleanup Tool

Automated analysis and removal of dead code based on RuntimeSpy instrumentation data.

## Architecture

```
┌─────────────────────────────────────┐
│  1. Instrumentation Backend         │
│  - Collects execution frequency     │
│  - Endpoint: GET /stats/clean       │
└────────────┬────────────────────────┘
             │
             ↓
┌─────────────────────────────────────┐
│  2. delete-dead-code skill          │
│  - Analyzes instrumentation JSON    │
│  - Outputs recommendations JSON     │
│  - No code modifications            │
└────────────┬────────────────────────┘
             │
             ↓
┌─────────────────────────────────────┐
│  3. GitHub Action Workflow          │
│  - Applies recommendations          │
│  - Creates commit & PR              │
│  - In target repo (.github/workflows)
└─────────────────────────────────────┘
```

## Usage

### For RuntimeSpy's demo service

The workflow runs automatically:
- **Schedule**: Daily at 2 AM UTC
- **Manual**: `gh workflow run dead-code-cleanup.yml`

### For other services

**Option 1: Copy the skill to your repo**

```bash
cp RuntimeSpy/delete-dead-code OtherRepo/
```

Then create `.github/workflows/dead-code-cleanup.yml` in OtherRepo:

```yaml
name: Dead Code Cleanup
on:
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch:

jobs:
  cleanup:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      
      - name: Fetch instrumentation report
        run: curl -s http://YOUR_BACKEND/stats/clean > report.json
      
      - name: Analyze dead code
        run: |
          chmod +x ./delete-dead-code
          ./delete-dead-code --limit 5 report.json > recommendations.json
      
      - name: Apply deletions and create PR
        # ... (copy the "Apply deletions" step from RuntimeSpy's workflow)
```

**Option 2: Reference from RuntimeSpy**

```yaml
- name: Get skill
  run: |
    curl -s https://raw.githubusercontent.com/YOUR_ORG/RuntimeSpy/main/delete-dead-code > /tmp/delete-dead-code
    chmod +x /tmp/delete-dead-code

- name: Analyze
  run: /tmp/delete-dead-code --limit 5 report.json > recommendations.json
```

**Option 3: Install as package** (future)

```bash
pip install delete-dead-code
delete-dead-code --limit 5 instrumentation.json
```

## Skill API

### Input
JSON instrumentation report with:
- `summary`: Total nodes, executed nodes, dead nodes
- `graph.nodes[]`: Each node with `path`, `start_line`, `end_line`, `frequency`

### Output
JSON recommendations with:
- `status`: "success" or "error"
- `groups[]`: Each group with `file`, `deletions[]`, `confidence`, `risk`

### Command line

```bash
# Analyze from file
./delete-dead-code --limit 5 report.json

# Analyze from stdin
curl http://backend/stats/clean | ./delete-dead-code --limit 5

# Verbose output
./delete-dead-code --verbose --limit 3 report.json

# Save to file
./delete-dead-code report.json --output recommendations.json
```

## Safety

- ✅ Analyzes only code with `frequency=0` (never executed)
- ✅ Skill does NOT modify code
- ✅ Workflow creates PR for human review
- ✅ Easy to revert (just close/revert the PR)
- ✅ No external dependencies (pure Python)

## How it works

1. **Instrumentation backend** collects execution data → frequency counts
2. **delete-dead-code skill** analyzes → finds nodes with frequency=0
3. **Groups** deletions by file → creates manageable PRs
4. **GitHub Action** applies deletions → creates PR
5. **Developer** reviews → approves or rejects

## Example

```bash
# 1. Get instrumentation data
curl http://backend/stats/clean > report.json

# 2. Analyze with skill
./delete-dead-code --limit 3 report.json

# Output:
{
  "status": "success",
  "groups": [
    {
      "file": "src/api/admin.py",
      "deletions": [{"start_line": 1, "end_line": 83}],
      "total_lines": 83,
      "confidence": 95,
      "risk": 2
    }
  ]
}

# 3. GitHub Action applies → creates PR with deletions
```

## Troubleshooting

**No dead code found?**
- Run more diverse test traffic
- Check instrumentation is collecting data
- Verify report has nodes with frequency=0

**Wrong deletions?**
- Review recommendations JSON before merge
- The skill only analyzes frequency=0 nodes
- Deletions are conservative (complete blocks only)

**Workflow failed?**
- Check GitHub Actions logs
- Ensure backend is reachable
- Verify `gh` CLI is authenticated

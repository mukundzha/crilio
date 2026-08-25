# Crilio

**The CI/CD quality gate for AI — pytest for prompts.**

Crilio stops prompt regressions from reaching production. You version a `crilio.yaml` of prompts + natural-language rules, Crilio calls your model (BYOK), judges the response with another model, and reports `PASS / FAIL` per rule. Failures block PRs in GitHub Actions — locally they just report.

## Quick Start

```bash
pip install crilio 

export OPENAI_API_KEY="sk-proj-..."   # or ANTHROPIC_API_KEY
# .env also works — never commit it

crilio init                            # creates crilio.yaml (default max_monthly_budget_usd: 10.0)
crilio run --dry-run                   # validate without API calls
crilio run                             # Target → Judge → gate
```

`crilio` with no args shows status, budget, and next steps.

## Usage

```
crilio init      [--force] [--yes]
crilio run       [-c crilio.yaml] [-m gpt-4o] [--judge-model gpt-4o-mini] [--verbose] [--json] [--dry-run]
crilio validate  [-c crilio.yaml] [--json]
crilio --version
crilio --docs    # full interactive guide
```

- `init`: creates `crilio.yaml`. `--force` overwrites; if `.github/workflows/crilio.yml` exists and `--force`, you’re asked `replace it? y/n`. `--yes` for CI (skips GHA prompt).
- `run`: executes the gate. `exit 0` pass, `exit 1` fail (only when `GITHUB_ACTIONS=true` or workflow exists — locally a failed gate warns but doesn’t block).
- `validate`: checks config/provider/models/rules/budget without API calls. `exit 0` valid, `2` invalid.
- `--dry-run` on `run` validates config + provider without calling models. `--json` emits machine-readable output, `--verbose` shows full responses.

Provider keys are **never** a flag — use env:

| Provider | Env | Default target | Default judge |
|---|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` | `gpt-4o-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-3-5-sonnet-latest` | `claude-3-5-haiku-latest` |

`provider` is inferred from env if not set in `crilio.yaml`.

### Budget gate

`settings.max_monthly_budget_usd: 10.0` is the monthly cap. Every test prints:

```
🧪 Crilio Test Runner
Budget: $0.00 / $10.00 (0%)
Test 1: Refund Policy ✅ ($0.06)
   → Budget: $0.06 / $10.00 (0.6%)
Final Budget: $0.18 / $10.00 (1.8%)
Remaining: $9.82
```

If `total_cost > max_monthly_budget_usd`, the run stops immediately, shows only completed tests, and fails the gate. Remove the line (or leave it blank `max_monthly_budget_usd:`) for no limit. Costs are estimated from published per-million-token prices; unknown models count as `$0`.

## Examples

Minimal `crilio.yaml`:

```yaml
settings:
  target_model: gpt-4o
  judge_model: gpt-4o-mini
  max_monthly_budget_usd: 10.0

tests:
  - name: Refund Policy Check
    prompt: How long do I have to return a product?
    rules:
      - Must mention the 30-day return window.
      - Must NOT mention competitor names.
```

JSON enforcement:

```yaml
  - name: JSON Format Check
    prompt: |
      Return ONLY this JSON and nothing else: {"status": "shipped", "order_id": "12345"}
    rules:
      - Must return valid JSON with keys 'status' and 'order_id'.
      - Must NOT include apologies or extra prose.
```

Run variants:

```bash
crilio run --dry-run --json
crilio run -c tests/crilio.yaml --model gpt-4o --verbose
crilio validate --json
crilio run --json > results.json
```

Per-test overrides (advanced):

```yaml
tests:
  - name: Anthropic smoke
    provider: anthropic
    model: claude-3-5-sonnet-latest
    judge_model: claude-3-5-haiku-latest
    prompt: Say hello
    rules: [Must contain hello]
```

## Configuration

```yaml
provider: openai              # optional, inferred from env
model: gpt-4o-mini
judge_model: gpt-4o-mini
base_url: https://api.openai.com/v1
system: You are helpful...    # global system prompt
settings:
  target_model: gpt-4o
  judge_model: gpt-4o-mini
  max_monthly_budget_usd: 10.0 # delete line for unlimited
tests:
  - name: "unique name"       # must be unique
    prompt: "..."
    system: "..."             # optional per-test override
    provider/model/judge_model: ... # optional per-test override
    rules:
      - Must mention X.
      - Must NOT mention Y.  # Judge is literal, temp 0. One idea per rule, 2-5 per test.
```

## GitHub Actions

`crilio init` (interactive) can create `.github/workflows/crilio.yml`:

```yaml
name: Crilio AI Tests
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.10' }
      - run: pip install crilio
      - run: crilio run
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

Add the secret matching your provider. A `FAIL` gate exits `1` and blocks the PR.

## Development

```bash
git clone https://github.com/crilio/crilio && cd crilio
python -m venv .venv && source .venv/bin/activate
pip install -e . && pip install pytest
pytest -q
crilio run --dry-run
```

## Notes

- BYOK — you pay the provider directly (~$0.002/test on `gpt-4o-mini`). No hosted eval platform.
- Judge uses `instructor` + Pydantic for strict JSON (`rule_passed: bool`), eliminating flaky free-text verdicts.
- `crilio init --force` asks before overwriting an existing workflow; `crilio run` without GHA never hard-fails the shell.

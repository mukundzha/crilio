<div align="center">
<img src="./assests/readme_logo.png" alt="Crilio" width="170" />
<h1 style="margin: -4px 0 0 0;">crilio</h1>
<p style="margin: 6px 0 0 0;"><strong>The CI/CD quality gate for AI — pytest for prompts.</strong></p>

<p style="margin: 12px 0 0 0; font-size: 14px;">If Crilio helps you, please ⭐ <a href="https://github.com/mukundzha/crilio"><strong>star this repo</strong></a> — it helps other devs find it and motivates me to keep building.</p>

<p style="margin: 6px 0 0 0; font-size: 14px;">☁️ <a href="https://tally.so/r/0QRj4j">Join the Crilio Cloud Waitlist</a> (Get 40% off team dashboards & analytics when we launch)</p>

  <p align="center" style="margin-top: 14px;">
    <a href="https://pypi.org/project/crilio/"><img src="https://img.shields.io/pypi/v/crilio?style=flat-square&label=PyPI&color=black" alt="PyPI"/></a>
    <a href="https://pypi.org/project/crilio/"><img src="https://img.shields.io/pypi/pyversions/crilio?style=flat-square&label=python&color=black" alt="Python"/></a>
    <a href="./LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-black?style=flat-square" alt="License"/></a>
  </p>
</div>

---

**Crilio stops prompt regressions from reaching production.** Version your prompts + natural-language rules in `crilio.yaml` — Crilio calls your model, judges every response with an LLM, and reports `PASS / FAIL` per rule.

---

### ✨ Features

- **LLM-as-a-Judge** — Strict Pydantic-verified verdicts (`rule_passed: bool`), temp 0. No flaky free-text parsing.
- **BYOK** — Your keys, your bill. OpenAI + Anthropic. Typically < $0.01 / test on `gpt-4o-mini`.
- **CI/CD Native** — `exit 1` blocks PRs in GitHub Actions. Locally it warns but never blocks.
- **PR Comments** — Auto-posts formatted failure details to the PR when running in Actions (`GITHUB_TOKEN`, silent fail, never blocks gate).
- **Leak Guard** — Rejects `crilio.yaml` containing `sk-...`/`api_key` — keys must be in `.env`/Secrets, never committed.
- **Local Bots** — `target: {command: "python bot.py '{{prompt}}'"}` runs any local model (Ollama/vLLM) via stdout → Judge, `$0` target.
- **Skip & List** — `skip: true` per-test to pause, `crilio ls [--tag] [--json]` to preview tests without running.
- **Diff** — `crilio diff --base main` shows prompt/rule changes between git refs (`+`/`-` per rule, not whole list).
- **Budget Guard** — `max_monthly_budget_usd` halts the run when cost exceeds cap. Delete the line or leave it blank for unlimited.
- **Rich Terminal UI** — `crilio` (no args) shows a `STATUS` / `EXAMPLES` / `COMMANDS` homepage; `crilio run` prints a `Test / Prompt / Output / Verdict` result table and a `Gate PASS` / `Gate FAIL` summary footer.
- **Fail-fast** — `crilio run --fail-fast` stops after the first failure.

---

### 🚀 Quick Start

```bash
pip install crilio

export OPENAI_API_KEY="sk-proj-..."  # or ANTHROPIC_API_KEY — .env also works
crilio init                          # creates crilio.yaml
crilio run --dry-run                 # validate without API calls
crilio run                           # Target → Judge → gate
```

> `crilio` with no args shows status, config, and next steps.

---

### ⚙️ Usage

| Command | Description |
|---|---|
| `crilio init [--force] [--yes]` | Create `crilio.yaml` + optional GitHub Actions workflow |
| `crilio ls [-c FILE] [--tag TAG] [--json]` | List tests — preview without running |
| `crilio diff [--base REF] [-c FILE] [--json] [--fail-on-change]` | Show prompt/rule diff between git refs |
| `crilio run [-c FILE] [-m MODEL] [--judge-model MODEL] [--verbose] [--json] [--dry-run] [--tag TAG] [--fail-fast]` | Run gate — `0` pass, `1` fail (only in CI) · `--tag` filters to `tags: [TAG]` tests |
| `crilio validate [-c FILE] [--json]` | Validate config without API calls — `0` valid, `2` invalid |
| `crilio --version` / `crilio --docs` | Version / full interactive guide |

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI — default target `gpt-4o-mini`, judge `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic — default target `claude-3-5-sonnet-latest`, judge `claude-3-5-haiku-latest` |

Provider is inferred from env if not set in `crilio.yaml`. Keys are **never** flags — env only.

<details>
<summary><strong>crilio.yaml</strong></summary>

```yaml
# ==========================================
# Crilio Configuration (crilio.yaml)
# The CI/CD quality gate for AI.
# ==========================================

settings:
  # Provider is automatically inferred from your API key (OPENAI_API_KEY or ANTHROPIC_API_KEY)
  provider: openai

  # The AI model you are testing (Target)
  target_model: gpt-4o-mini

  # The fast/cheap model that grades the tests (Judge)
  judge_model: gpt-4o-mini

  # Hard limit on API spending per month (in USD) to prevent surprises
  max_monthly_budget_usd: 10.0

# ==========================================
# Test Cases
# ==========================================

tests:
  # Test 1: Semantic Rule Check (API)
  - name: "Refund Policy Check"
    prompt: "How long do I have to return a product?"
    rules:
      - "Must mention the 30-day return window."
      - "Must NOT mention competitor names like Amazon or Walmart."
    tags:
      - "refund"
      - "policy"
      - "customer service"

  # Test 2: JSON Formatting Enforcement (API)
  - name: "JSON Format Check"
    prompt: "Return my user status as JSON."
    rules:
      - "Must return valid JSON with keys 'status' and 'user_id'."
      - "Must NOT include apologies or extra prose."
    tags:
      - "json"
      - "formatting"

  # Test 3: Local Model Execution (Zero API Cost, Total Privacy)
  # Uncomment the lines below to test a local model via Ollama!
  # - name: "Local Llama 3 Check"
  #   prompt: "Say hello in a professional tone."
  #   target:
  #     command: "ollama run llama3 '{{prompt}}'"
  #   rules:
  #     - "Must contain the word 'Hello' or 'Hi'."
  #   tags:
  #     - "local"
  #     - "llama"
```

Keys:

- `provider`: `openai` or `anthropic`
- `model` / `judge_model`: override defaults
- `settings.max_monthly_budget_usd`: monthly cap — run stops when exceeded, shows `Budget: $spent / $cap (pct)` after each test
- `system`: global system prompt (passed to Target); per-test `system` overrides
- `tests[].name` must be unique
- `tests[].rules` are natural language — Judge is literal. Use `Must` / `Must NOT`.
- `tests[].tags` optional list — filter with `crilio run --tag smoke` (no flag = all, missing tags = skipped when filtered)
- `tests[].target.command` — local CLI e.g. `python bot.py '{{prompt}}'` or `ollama run llama3 '{{prompt}}'`, `{{prompt}}` → `shlex.quote`, no placeholder → stdin pipe, `timeout 30s`, `$0` target, injection-safe
- `tests[].skip` — set `skip: true` to pause a test (shows SKIPPED)
- Per-test `provider/model/judge_model/system/tags/target/skip` overrides global (advanced, needs its own key).
- **Leak Guard:** `crilio.yaml` containing `sk-...` or `api_key:` fails `validate`/`run` (exit 2) — use `.env` / Secrets, never commit keys.

</details>

<details>
<summary><strong>🦙 Ollama template — test any local model</strong></summary>

```yaml
# 1. ollama serve & ollama pull llama3  (or mistral, qwen2, etc.)
# 2. crilio.yaml:
settings:
  target_model: gpt-4o
  judge_model: gpt-4o-mini

tests:
  - name: Ollama Refund
    prompt: "How long do I have to return a product?"
    target:
      command: "ollama run llama3 '{{prompt}}'"  # any model: mistral, qwen2, gemma
      # no placeholder also works → stdin: command: "ollama run llama3"
    rules:
      - "Must mention the 30-day return window."
    tags: ["ollama", "local"]

# 3. export OPENAI_API_KEY="sk-..."  # Judge still API
# 4. crilio run --tag ollama --verbose
```

</details>

---

### 🔄 CI/CD Integration

`crilio init` can scaffold this for you. Or drop in `.github/workflows/crilio.yml`:

```yaml
name: Crilio AI Tests
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write  # for PR failure comments
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install crilio
      - run: crilio run
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}  # auto-provided for PR comments
```

Add the secret matching your provider. A `FAIL` gate exits `1` and blocks the PR. On failure in Actions, Crilio auto-posts a `🛑 Crilio AI Test Failed` comment (test / rule / AI response / reason) via `GITHUB_TOKEN` + `GITHUB_REPOSITORY` / `GITHUB_REF` (`refs/pull/12/merge` → `12`) — silent fail on API error (timeout/401) and locally, never blocks the gate.

---

### 📄 License

AGPL-3.0 — see [LICENSE](./LICENSE).

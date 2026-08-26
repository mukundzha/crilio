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
- **Budget Guard** — `max_monthly_budget_usd` halts the run when cost exceeds cap. Delete the line or leave it blank for unlimited.
---

### 🚀 Quick Start

```bash
pip install crilio

export OPENAI_API_KEY="sk-proj-..."  # or ANTHROPIC_API_KEY — .env also works
crilio init                          # creates crilio.yaml
crilio run --dry-run                 # validate without API calls
crilio run                           # Target → Judge → gate
```

> `crilio` with no args shows status, budget, and next steps.

---

### ⚙️ Usage

| Command | Description |
|---|---|
| `crilio init [--force] [--yes]` | Create `crilio.yaml` + optional GitHub Actions workflow |
| `crilio run [-c FILE] [-m MODEL] [--judge-model MODEL] [--verbose] [--json] [--dry-run]` | Run gate — `0` pass, `1` fail (only in CI) |
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
settings:
  target_model: gpt-4o
  judge_model: gpt-4o-mini
  max_monthly_budget_usd: 10.0  # delete or leave blank for unlimited

tests:
  - name: Refund Policy Check
    prompt: How long do I have to return a product?
    rules:
      - Must mention the 30-day return window.
      - Must NOT mention competitor names.

  - name: JSON Format Check
    prompt: |
      Return ONLY this JSON and nothing else: {"status": "shipped", "order_id": "12345"}
    rules:
      - Must return valid JSON with keys 'status' and 'order_id'.
      - Must NOT include apologies or extra prose.
```

Per-test overrides: `provider`, `model`, `judge_model`, `system` can be set per test.

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

---

### 📄 License

AGPL-3.0 — see [LICENSE](./LICENSE).

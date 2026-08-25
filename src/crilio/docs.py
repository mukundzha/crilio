from __future__ import annotations

import io
import re
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

DOCS = r"""
# CRILIO — The CI/CD Quality Gate for AI
> **Stop shipping prompt regressions to production.** `pytest` for prompts.

---

## 1 · Concept — Why Crilio Exists

Traditional code: `assert add(2,2)==4` always passes. Break it → CI fails.

LLMs are non-deterministic. One word makes a bot "friendlier" and it **hallucinates 60-day refunds**, leaks **competitor pricing**, or returns **prose instead of JSON** — breaking your parser.

Teams test this by pasting 5 prompts in a playground. Unscalable, unreviewable, terrifying for B2B.

**Crilio closes the gap:** One `crilio.yaml` contract, deterministic gate, no infra cost (BYOK).

| Without Crilio | With Crilio |
|---|---|
| Manual playground checks | `crilio.yaml` versioned in git, PR-reviewable |
| Silent prod regressions | `crilio run` blocks PR on `exit 1` |
| Pay for hosted eval platform | BYOK — you pay provider directly (~$0.002/test) |

---

## 2 · How It Works — 4 Steps

```
1. Contract  crilio.yaml  (prompt + rules)        → versioned, human-readable
2. Target    BYOK chat.completions call          → sends prompt to YOUR model
3. Judge     LLM-as-a-Judge via instructor       → {"rule_passed": true/false} strict JSON
4. Gate      Rich table ● PASS/FAIL per rule     → exit 0 PASS / 1 FAIL blocks CI
```

Why strict `instructor`? LLMs ramble. Pydantic validation forces JSON, eliminates `mostly good → PASS` flakiness.

---

## 3 · Quickstart — 5 Steps (export method)

```bash
# Step 1: Install
pip install crilio

# Step 2: Add a provider API key (BYOK — never in code)
export OPENAI_API_KEY="sk-proj-xxxxx..."
# Or:
export ANTHROPIC_API_KEY="sk-ant-xxxxx..."
# → add to .env locally, and the matching GitHub Secret for CI

# Step 3: Initialize config
crilio init                         # creates crilio.yaml with dummy test

cat crilio.yaml

# Step 4: Run locally
crilio run --dry-run                # validate without API
crilio run                          # Target → Judge → ✅/❌ gate
crilio run --verbose --json > results.json
```

`crilio --docs` shows this guide. `crilio --help` shows `init` + `run` only.

---

## 4 · Configuration — crilio.yaml

No `crilio.yaml` initially — `crilio init` creates it. Minimal file:

```yaml
tests:
  - name: "Hello"
    prompt: "Say hello"
    rules: ["Must contain hello"]

# Recommended global (single provider for all tests):
provider: openai
model: gpt-4o-mini
judge_model: gpt-4o-mini
system: "You are helpful..."
```

Example configuration:

```yaml
settings:
  target_model: "gpt-4o"
  judge_model: "gpt-4o-mini"
  max_monthly_budget_usd: 100.0

tests:
  - name: "Refund Policy Check"
    prompt: |
      You are Acme Store support. Policy: 30-day returns.
      Customer asks: "How long do I have to return a product?"
      Answer concisely, mention the 30-day window. Do not mention competitors.
    rules:
      - "Must mention the 30-day return window."
      - "Must NOT mention competitor names like Amazon or Walmart."
      - "Tone must be polite and professional."

  - name: "JSON Format Check"
    prompt: |
      Return ONLY this JSON and nothing else: {"status": "shipped", "order_id": "12345"}
    rules:
      - "Must return valid JSON with keys 'status' and 'order_id'."
      - "Must NOT include apologies or extra prose."
```

Keys:
- `provider`: `openai` or `anthropic`
- `model` / `judge_model`: override defaults
- `settings.max_monthly_budget_usd`: monthly cap — run stops when exceeded, shows Budget: $spent / $cap (pct) after each test
- `system`: global system prompt (passed to Target); per-test `system` overrides
- `tests[].name` must be unique
- `tests[].rules` are natural language — Judge is literal. Use `Must` / `Must NOT`.
- Per-test `provider/model/judge_model/system` overrides global (advanced, needs its own key).


---

## 5 · Commands — Only 2 (export method)

| Command | What it does | Key flags |
|---|---|---|
| `crilio init` | Create `crilio.yaml` + optionally `.github/workflows/crilio.yml` | `--yes` `--force` |
| `crilio validate` | Validate config without calling APIs | `-c --config` `--json` |
| `crilio run` | Run gate: Target → Judge → report → exit 0/1 | `-c --config` `--model` `--judge-model` `--verbose` `--json` `--dry-run` |
| `crilio --docs` | Show this guide | — |

Key is **never** a flag — use `export OPENAI_API_KEY=sk-...` (see Step 2). No `--api-key`.

Examples:
```bash
export OPENAI_API_KEY=sk-proj-...   # Step 2
crilio run --dry-run
crilio run                          # 5 steps: read → target → judge → report → gate (only if GHA enabled)
crilio run --model gpt-4o --verbose
```

---

## 6 · Providers — OpenAI and Anthropic

| Provider | Env Key | Default target | Default judge |
|---|---|---|---|
| `openai` | `OPENAI_API_KEY=sk-...` | `gpt-4o` | `gpt-4o-mini` |
| `anthropic` | `ANTHROPIC_API_KEY=...` | `claude-3-5-sonnet-latest` | `claude-3-5-haiku-latest` |

`export` only — no `--api-key` flag. Add to `.env` locally, `GitHub Secrets → OPENAI_API_KEY` for CI (see Step 5 workflow `env: OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}`). BYOK — never stored by us, `.env` gitignored.

List models: `curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"`

---

## 7 · Writing Good Rules

- Be literal: `Must mention 30-day` fails if 30 absent. `Must NOT mention Amazon` fails if word appears.
- One idea per rule, 2-5 rules per test.
- Use severity via phrasing: `Must` (hard fail) vs `Should ideally`.
- Judge is strict, temperature 0, 1-sentence reasoning shown in table `Reason` column.
- For JSON: also test `Must NOT include apologies` — catches prose leaks.

---

## 8 · GitHub Actions — Block PRs

```yaml
# .github/workflows/crilio.yml
name: crilio gate
on: [pull_request]
jobs:
  crilio:
    runs-on: ubuntu-latest
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
```

`crilio init` asks whether to create this workflow when run interactively. Add
the secret matching your configured provider. The workflow blocks the pull request when `crilio run` exits 1. There is no bundled
`action.yml` or PR-comment integration.

---

## 9 · Files & Project Structure

```
src/crilio/
  cli.py      Typer + Rich (init/run/docs, gate, --json)
  config.py   PyYAML → Pydantic (crilio.yaml)
  setup.py    provider/key persistence helpers for integrations
  provider.py openai resolution
  target.py   BYOK chat.completions (system prompt, temperature 0)
  judge.py    instructor strict JudgeVerdict
  docs.py     this guide
```

---

## 10 · Development & Release

```bash
git clone https://github.com/crilio/crilio && cd crilio
python -m venv .venv && source .venv/bin/activate
pip install -e . && pip install pytest
pytest -v
crilio run --dry-run
crilio run   # needs OPENAI_API_KEY
```

Release: `python -m build && twine upload dist/*` → `pip install crilio`

---

## 11 · Cost & Roadmap

- Judge ~$0.002/test (`gpt-4o-mini`), 10k tests ≈ $20 — you pay provider.
- Roadmap: `target.command` (local bot), Cloud dashboard (history), Stripe license, self-hosted Judge.

---

*Tip: Start with the generated config, make one prompt change, and run the gate before shipping.*
"""

def _render_lines(width: int = 100) -> list[str]:
    buf = io.StringIO()
    c = Console(file=buf, width=width, force_terminal=True, legacy_windows=False)
    c.print(Markdown(DOCS, hyperlinks=True))
    return buf.getvalue().splitlines()


def _get_key() -> str:
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch += sys.stdin.read(2)
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        try:
            return input().strip().lower()[:1] or " "
        except EOFError:
            return "q"


def show_docs(console: Console | None = None) -> None:
    c = console or Console()
    is_tty = sys.stdout.isatty() and sys.stdin.isatty()

    if not is_tty:
        c.print(Markdown(DOCS, hyperlinks=True))
        return

    lines = _render_lines(width=c.width if c.width else 100)
    total = len(lines)
    h = c.size.height if c.size.height > 4 else 24
    view_h = max(8, h - 3)
    offset = 0

    with c.screen(hide_cursor=True):
        while True:
            c.clear()
            end = min(offset + view_h, total)
            chunk = "\n".join(lines[offset:end])
            pct = int(end / total * 100) if total else 100
            bar = f"  [dim]{offset+1}-{end}/{total} {pct}%[/]  [bright_cyan]↑/k[/] up  [bright_cyan]↓/j/space[/] down  [bright_cyan]PgUp/PgDn[/]  [bright_cyan]g/G[/] top/bottom  [bright_cyan]q[/] quit  "
            c.file.write(chunk + "\n\n")
            c.print(Panel(bar, border_style="bright_black", padding=(0, 1), height=3))
            k = _get_key()
            if k in ("q", "Q", "\x03", "\x04"):
                break
            elif k in ("\x1b[A", "k", "K"):
                offset = max(0, offset - 1)
            elif k in ("\x1b[B", "j", "J", " ", "\r", "\n"):
                offset = min(max(0, total - view_h), offset + 1)
            elif k == "\x1b[5~":
                offset = max(0, offset - view_h)
            elif k == "\x1b[6~":
                offset = min(max(0, total - view_h), offset + view_h)
            elif k in ("b", "B", "\x1b[5~"):
                offset = max(0, offset - view_h)
            elif k in ("g", "0"):
                offset = 0
            elif k in ("G", "$"):
                offset = max(0, total - view_h)

# Crilio

**Test your AI prompts before they reach your users.**

Crilio helps you check that an AI assistant gives the answers you expect. You write a few prompts and rules in `crilio.yaml`, then Crilio runs them and shows which rules passed or failed.

[![PyPI](https://img.shields.io/pypi/v/crilio?style=flat-square)](https://pypi.org/project/crilio/)
[![Python](https://img.shields.io/pypi/pyversions/crilio?style=flat-square)](https://pypi.org/project/crilio/)
[![License: AGPLv3](https://img.shields.io/badge/License-AGPLv3-blue.svg?style=flat-square)](LICENSE)

## Why use Crilio?

AI responses can change when you update a prompt or model. Crilio helps you catch problems such as:

- a refund answer with the wrong number of days;
- an answer that mentions a competitor;
- a response that is not valid JSON;
- a reply that is not polite or does not follow your instructions.

Your tests stay in your project, so they can be reviewed and run alongside your code.

## Get started

### 1. Install Crilio

```bash
pip install crilio
```

### 2. Add your provider key

```bash
export OPENAI_API_KEY="sk-proj-..."
# Or:
export ANTHROPIC_API_KEY="sk-ant-..."
```

You can also put the key in a `.env` file. Do not commit that file.

### 3. Create your tests

```bash
crilio init
```

This creates `crilio.yaml` with an example you can edit.

### 4. Check and run your tests

```bash
# Check your file without using the API
crilio run --dry-run

# Run the tests
crilio run
```

You will see each test, its response, and whether each rule passed or failed.

## Your `crilio.yaml`

Here is a small example:

```yaml
settings:
  target_model: "gpt-4o"
  judge_model: "gpt-4o-mini"

tests:
  - name: "Refund answer"
    prompt: "How long do I have to return a product?"
    rules:
      - "Must mention the 30-day return window."
      - "Must NOT mention competitor names."

  - name: "JSON answer"
    prompt: |
      Return only this JSON:
      {"status": "shipped", "order_id": "12345"}
    rules:
      - "Must return valid JSON with status and order_id."
      - "Must NOT include extra text."
```

Write rules as simple, clear instructions:

```yaml
rules:
  - "Must mention the support email address."
  - "Must NOT make up a delivery date."
```

Each test needs a unique `name`, a `prompt`, and at least one rule.

## Commands

### `crilio init`

Creates a new `crilio.yaml`.

Use `--force` if you want to replace an existing file. Use `--yes` when running without questions, such as in a script.

### `crilio run`

Runs the tests in `crilio.yaml`.

```bash
crilio run
crilio run --dry-run
crilio run --verbose
crilio run --json
crilio run --config tests/crilio.yaml
crilio run --model gpt-4o
crilio run --judge-model gpt-4o-mini
```

- `--dry-run` checks the file without calling OpenAI.
- `--verbose` shows the complete AI response.
- `--json` prints results in a format suitable for other tools.
- `--config` uses a different YAML file.
- `--model` changes the model that answers your prompt.
- `--judge-model` changes the model that checks the answer.

You can also use:

```bash
crilio --help
crilio --version
crilio --docs
```

## GitHub Actions

When you run `crilio init` in a terminal, Crilio asks whether you want to create a GitHub Actions workflow for pull requests. The workflow runs:

```bash
pip install crilio
crilio run
```

Add `OPENAI_API_KEY` to your repository secrets. A failed test blocks the pull request in GitHub Actions. Locally, a failed test is reported without blocking your shell workflow.
For Anthropic configurations, add `ANTHROPIC_API_KEY` instead.

## Supported provider

Crilio currently supports **OpenAI** and **Anthropic**.

| Provider | Environment variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |

Your key is used to communicate directly with the selected provider. Crilio does not receive or store it.

## Development

```bash
git clone https://github.com/crilio/crilio
cd crilio
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install pytest
pytest -q
```

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).

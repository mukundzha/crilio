# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- TBD

## [0.0.6] - 2026-08-28

### Added
- **`crilio diff` — prompt/rule diff between git refs** — `crilio diff --base main` shows `Test | Field | Change` with `+ added` / `- removed` per rule (not whole list dump), `Panel` titled `Diff: main → HEAD`, `display_rows` count (`1 change` / `2 changes`), `sorted` tests/fields, `120` chars, `target`/`tags`/`prompt` diff, `--json` + `--fail-on-change`
- **`--fail-fast` for `crilio run`** — `crilio run --fail-fast` stops after first `FAIL` (both `API` and `target.command` + target error), `Fail-fast: stopping after 1/3 tests`, before budget check

### Changed
- `README` + `docs.py` — added `Diff` bullet + `crilio diff` row in Usage, `crilio diff` in Commands table + examples
- `src/crilio/cli.py` — `diff` command (`subprocess` `git show`, fallback `origin/main`/`HEAD~1`/`HEAD`), `--fail-fast` in `run` loop (3 spots: `is_command` target error, `API` target error, success path)

### Removed
- **Telemetry** — `src/crilio/telemetry.py` deleted, all `track()` + `--off-tracking` + `Settings.telemetry` + `POSTHOG` + README/docs mentions removed (`0` network, `0` dep)

## [0.0.5] - 2026-08-27

### Added
- **Telemetry** — anonymous PostHog `cli_command`/`cli_run_*`/`cli_validate` events (`POSTHOG_API_KEY`, `us.i.posthog.com`, no prompts/keys, `distinct_id` in `~/.config/crilio/telemetry_id`); production ready with 4 kill-switches: `crilio --off-tracking` (global) / `crilio <cmd> --off-tracking` (per-command) / `CRILIO_DISABLE_TELEMETRY=1`/`DO_NOT_TRACK=1` / `settings: telemetry: false` (all silent, never blocks)
- **Skip & List** — `skip: true` per-test to pause (shows `SKIPPED`), `crilio ls` / `crilio list` (`--tag`, `--json`, `--off-tracking`) to preview without cost; `run` respects `skip`
- **Ollama template** — `README` `🦙 Ollama template` (`ollama run llama3 '{{prompt}}'`, `{{prompt}}` → `shlex.quote`, stdin fallback, `crilio run --tag ollama`)

### Changed
- `src/crilio/config.py` — `Settings.telemetry: bool = True`, `TestCase.skip: bool = False`
- `src/crilio/telemetry.py` — new, `us.i.posthog.com` default, `1s` timeout, `CRILIO_TELEMETRY_DEBUG=1`
- `src/crilio/cli.py` — global + per-command `--off-tracking`, `run`/`validate`/`ls` respect `settings.telemetry: false`, `ls`/`list` commands
- `README` + `docs.py` — Telemetry, Local Bots, Ollama, Skip & List, `crilio ls` in Usage

## [0.0.4] - 2026-08-26

### Added
- **`target: {command}` local bots** — `target: {command: "python bot.py '{{prompt}}'"}` (also shorthand `target: "echo hi"`) runs any CLI (Ollama/vLLM/`curl`) via `stdout → Judge`, `{{prompt}}` → `shlex.quote` (`'{{prompt}}'`/`"{{prompt}}"`/`{{prompt}}` all safe), no placeholder → stdin pipe, `timeout 30s`, `$0` target cost, injection-safe; `bot.py` example (argv + stdin)
- **Leak Guard** — `load_config` rejects `crilio.yaml` containing `sk-...`/`api_key:` (exit 2) — use `.env`/Secrets
- **Workflow** — `crilio init` now scaffolds `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` for PR comments

### Changed
- `README` + `docs.py` — added Local Bots feature, `crilio.yaml` example with `target.command`, How It Works `Target: BYOK *or* local`, Keys, Files & Project Structure, Roadmap shipped
- `src/crilio/config.py` — `TargetCommand` + `TestCase.target` (string shorthand coerced)
- `src/crilio/target.py` — `call_target_command` (shlex, subprocess, timeout)
- `src/crilio/cli.py` — `run()` branches `command` vs API (Judge still API), `$0` cost, same PR comment/budget/tag paths

## [0.0.3] - 2026-08-26

### Added
- **`--tag` filtering for `crilio run`** — `crilio run --tag smoke` runs only tests with `tags: ["smoke"]`; `tags` is optional per-test, no flag = all tests, missing tags = skipped when filtered; `DEFAULT_CONFIG_YAML` now includes `tags: ["smoke", "critical"]` example; `README` + `docs.py` updated
- **GitHub PR Commenter** — when `GITHUB_ACTIONS=="true"` and a rule fails, auto-posts `🛑 Crilio AI Test Failed` comment via `GITHUB_TOKEN` / `GITHUB_REPOSITORY` / `GITHUB_REF` (`refs/pull/12/merge` → `12`); 5s timeout, silent fail on 401/timeout/bad ref, never logs token, never blocks gate/exit code; requires `permissions: pull-requests: write` + `GITHUB_TOKEN` in workflow
- **Tests** — 13 new tests: config `tags` parsing, `init` tags, dry-run tag filtering/no-match/skip, PR commenter noop/posts/resilience/bad-ref/missing-env/never-logs-token + integration `run` failure posts comment

### Changed
- `README` features + CI workflow note PR comments; `docs.py` §8 updated with permissions + failure comment example
- `src/crilio/config.py` `TestCase` now supports `tags: Optional[list[str]]`

## [0.0.2] - 2026-08-25

### Added
- **Anthropic support** — `provider: anthropic` with `claude-3-5-sonnet-latest` (target) and `claude-3-5-haiku-latest` (judge), auto-inferred from `ANTHROPIC_API_KEY`
- **Cost tracking & Budget Guard** — per-test token usage, cost estimation (`cost.py`), `max_monthly_budget_usd` with `10.0` default; run halts when exceeded, blank or deleted line = unlimited
- **`crilio validate` command** — validates `crilio.yaml` without API calls (`--json`, exit `0`/`2`)
- **`--dry-run` for `crilio run`** — validates config + provider without calling models
- `crilio.yaml` generated by `crilio init` now includes `settings.max_monthly_budget_usd` and two starter tests

### Changed
- BYOK-only auth — keys via env (`.env` supported), never CLI flags; `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`
- `crilio init --force` now prompts before overwriting existing `.github/workflows/crilio.yml`
- Judge uses `instructor` + Pydantic strict `rule_passed: bool` at `temperature=0` for both providers
- Docs and CLI help refreshed for 0.0.2

### Fixed
- Provider resolution and model defaults for OpenAI/Anthropic

## [0.0.1] - 2026-08-24

### Added
- Initial release — `crilio init`, `crilio run` (Target → Judge → Gate), `crilio.yaml` with prompts + natural-language rules
- GitHub Actions workflow template on `pull_request`
- License AGPL-3.0-only

[Unreleased]: https://github.com/mukundzha/crilio/compare/v0.0.6...HEAD
[0.0.6]: https://github.com/mukundzha/crilio/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/mukundzha/crilio/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/mukundzha/crilio/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/mukundzha/crilio/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/mukundzha/crilio/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/mukundzha/crilio/releases/tag/v0.0.1

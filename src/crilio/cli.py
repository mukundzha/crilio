from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time
from typing import Optional

import yaml

import requests

import typer
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from crilio.__version__ import __version__
from crilio.config import DEFAULT_CONFIG_YAML, CrilioConfig, load_config
from crilio.judge import judge_rule
from crilio.provider import (
    PROVIDER_DEFAULTS,
    load_dotenv,
    make_client,
    resolve_for_test,
    resolve_provider,
)
from crilio.setup import mask_key
from crilio.target import call_target, call_target_command

app = typer.Typer(name="crilio", add_completion=False, no_args_is_help=False)
console = Console()
err_console = Console(stderr=True)


CRILIO_BANNER = r""" ██████  ████████  ████ ██       ████  ███████
██    ██ ██     ██  ██  ██        ██  ██     ██
██       ██     ██  ██  ██        ██  ██     ██
██       ████████   ██  ██        ██  ██     ██
██       ██   ██    ██  ██        ██  ██     ██
██    ██ ██    ██   ██  ██        ██  ██     ██
 ██████  ██     ██ ████ ████████ ████  ███████"""


def _section(c: Console, title: str) -> None:
    width = max(4, c.width if c.width else 80) - 4
    c.print(f"[bold #FF65C3]{title}[/]")
    c.print("[dim]─[/]" * (width // 2))


def _show_homepage():
    c = console
    c.print()
    w = c.width if c.width else 80
    if w >= 64:
        c.print(f"[bold #FF65C3]{CRILIO_BANNER}[/]")
    else:
        c.print("[bold #FF65C3]crilio[/]")
    c.print()

    n_tests = 0
    n_rules = 0
    provider = "openai"
    model = "gpt-4o"
    try:
        cfg = load_config("crilio.yaml")
        n_tests = len(cfg.tests)
        n_rules = sum(len(t.rules) for t in cfg.tests)
        provider = cfg.provider or "openai"
        model = cfg.model or "gpt-4o-mini"
        config_line = f"crilio.yaml found — {n_tests} test{'s' if n_tests != 1 else ''}, {n_rules} rule{'s' if n_rules != 1 else ''} · {provider}/{model}"
    except Exception:
        config_line = (
            "[bold #FF65C3]no crilio.yaml[/] · run [bold #FF65C3]crilio init[/]"
        )

    env_key, key = None, None
    for name, defaults in PROVIDER_DEFAULTS.items():
        k = os.getenv(defaults["env_key"], "")
        if k:
            env_key, key = defaults["env_key"], k
            break
    if key:
        key_line = f"{env_key} active ([bold #FF65C3]{mask_key(key)}[/])"
    else:
        key_line = "[bold #FF65C3]no key configured[/] · set [bold #FF65C3]OPENAI_API_KEY[/] or [bold #FF65C3]ANTHROPIC_API_KEY[/]"

    budget = None
    try:
        budget = load_config("crilio.yaml").max_monthly_budget_usd
    except Exception:
        budget = None
    if budget is not None:
        budget_line = f"$0.00 / ${budget:.2f} (0%)"
    else:
        budget_line = "not configured"

    _section(c, "STATUS")
    c.print(f"  config   {config_line}")
    c.print(f"  key      {key_line}")
    c.print(f"  budget   {budget_line}")
    c.print()

    _section(c, "EXAMPLES")
    examples = [
        ("crilio init", "Create crilio.yaml (+ GitHub Actions workflow)."),
        ("crilio run --dry-run", "Validate config without API calls."),
        ("crilio run", "Target → judge → gate (exit 1 blocks PRs in GHA)."),
        ("crilio run --tag smoke", 'Run only tests tagged "smoke".'),
        ("crilio diff --base main", "Diff prompts/rules vs a git ref."),
    ]
    for cmd, desc in examples:
        pad = max(1, 26 - len(cmd))
        c.print(f"  [bold #FF65C3]{cmd}[/] {' ' * pad}{desc}")
    c.print()

    _section(c, "COMMANDS")
    commands = [
        ("init", "Create crilio.yaml + optional .github/workflows/crilio.yml"),
        ("ls", "List tests in crilio.yaml (--tag, --json)"),
        ("diff", "Diff prompts/rules vs git ref (--base, --fail-on-change)"),
        ("validate", "Validate config without calling provider APIs"),
        ("run", "Run the gate: target → judge → pass/fail (--tag, --model, --dry-run)"),
        ("history", "Show recent runs from .crilio/history.jsonl"),
        ("report", "Generate HTML/JUnit report from last run"),
        ("--docs", "Full interactive guide"),
        ("--version", "Show version"),
    ]
    for cmd, desc in commands:
        pad = max(1, 12 - len(cmd))
        c.print(f"  [bold #FF65C3]{cmd}[/] {' ' * pad}{desc}")
    c.print()


def _post_github_pr_comment(
    test_name: str, rule_broken: str, ai_response: str, reason: str
):
    """
    Posts a formatted comment to the GitHub PR if running in GitHub Actions.
    Fails silently to ensure CLI resilience.
    """
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")
    ref = os.getenv("GITHUB_REF", "")
    if not all([token, repo, ref]):
        return
    try:
        pr_number = ref.split("/")[2]
    except IndexError:
        return
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    body = (
        f"### 🛑 Crilio AI Test Failed\n\n"
        f"**Test:** {test_name}\n"
        f"**Rule Broken:** {rule_broken}\n\n"
        f"**AI Response:**\n> {ai_response}\n\n"
        f"**Reason:** {reason}\n\n"
        f"_Please fix your prompt before merging._"
    )
    payload = {"body": body}
    try:
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception:
        console.print("[grey50]Warning: Failed to post GitHub PR comment.[/grey50]")


def version_callback(value: bool):
    if value:
        console.print(f"crilio {__version__}")
        raise typer.Exit()


def docs_callback(value: bool):
    if value:
        from crilio.docs import show_docs

        show_docs(console)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version",
        callback=version_callback,
        is_eager=True,
    ),
    docs: bool = typer.Option(
        None,
        "--docs",
        help="Show full documentation guide",
        callback=docs_callback,
        is_eager=True,
        hidden=True,
    ),
):
    load_dotenv()
    if ctx.invoked_subcommand is None and not version and not docs:
        _show_homepage()
        raise typer.Exit(0)


@app.command(hidden=True)
def docs():
    """Show full documentation — hidden, use --docs flag."""
    from crilio.docs import show_docs

    show_docs(console)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing crilio.yaml"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive, use defaults"),
    provider: str = typer.Option(None, "--provider", help="openai or anthropic"),
    model: str = typer.Option(None, "--model", "-m", help="Target model"),
    judge_model: str = typer.Option(None, "--judge-model", help="Judge model"),
    base_url: str = typer.Option(None, "--base-url", help="API base URL (e.g. https://api.groq.com/openai/v1)"),
):
    """Initialize crilio.yaml — Step 3 of setup."""
    dest = pathlib.Path("crilio.yaml")
    if dest.exists() and not force:
        err_console.print(f"[yellow]crilio.yaml already exists at {dest} — use --force to overwrite[/]")
        raise typer.Exit(1)
    text = DEFAULT_CONFIG_YAML
    if provider:
        text = text.replace("${CRILIO_PROVIDER:-openai}", provider)
    if model:
        text = text.replace("${CRILIO_MODEL:-openai/gpt-oss-120b}", model)
        text = text.replace("openai/gpt-oss-120b", model)
    if judge_model:
        text = text.replace("${CRILIO_JUDGE_MODEL:-openai/gpt-oss-120b}", judge_model)
    if base_url:
        text = text.replace("${CRILIO_BASE_URL:-https://api.groq.com/openai/v1}", base_url)
        text = text.replace("https://api.groq.com/openai/v1", base_url)
    if dest.exists() and force:
        dest.unlink()
    dest.write_text(text, encoding="utf-8")
    try:
        from crilio.config import load_config as _lc
        _cfg = _lc(str(dest))
        n = len(_cfg.tests)
    except Exception:
        n = text.count('- name:')
    console.print(f"[green]✓ Created {dest}[/] — {n} tests")
    console.print()
    console.print(
        Panel.fit(
            "  [yellow]⚠  Please check and modify [bold #FF65C3]crilio.yaml[/] according to your need[/]\n  [dim]Update prompts and rules to match your app, then run [bold #FF65C3]crilio run[/][/]",
            border_style="yellow",
            padding=(0, 2),
        )
    )
    console.print()
    console.print(
        "[dim]Next: set [bold #FF65C3]OPENAI_API_KEY[/] or [bold #FF65C3]ANTHROPIC_API_KEY[/] → [bold #FF65C3]crilio run --dry-run[/] → [bold #FF65C3]crilio run[/][/]"
    )

    try:
        is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        is_tty = False

    do_gha = False
    if yes:
        do_gha = False
    elif is_tty:
        try:
            from rich.prompt import Confirm

            if Confirm.ask(
                "Do you want to automatically setup GitHub Actions to run on every Pull Request?",
                default=False,
                console=console,
            ):
                do_gha = True
        except Exception:
            do_gha = False
    else:
        do_gha = False

    if do_gha:
        wf_dir = pathlib.Path(".github/workflows")
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_path = wf_dir / "crilio.yml"
        wf_content = """name: Crilio AI Tests
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
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
"""
        if wf_path.exists():
            if not force:
                console.print(f"[yellow]{wf_path} already exists — skipping[/]")
            else:
                should_overwrite = True
                if is_tty and not yes:
                    try:
                        from rich.prompt import Confirm

                        should_overwrite = Confirm.ask(
                            f"{wf_path} already exists — replace it?",
                            default=False,
                            console=console,
                        )
                    except Exception:
                        should_overwrite = False
                if should_overwrite:
                    wf_path.write_text(wf_content, encoding="utf-8")
                    console.print(
                        f"[green]✓ Created {wf_path}[/] — runs on every Pull Request"
                    )
                else:
                    console.print(
                        f"[yellow]Kept existing {wf_path} — not overwritten[/]"
                    )
        else:
            wf_path.write_text(wf_content, encoding="utf-8")
            console.print(f"[green]✓ Created {wf_path}[/] — runs on every Pull Request")
    else:
        if is_tty and not yes:
            console.print(
                "[dim]Skipped GitHub Actions setup — create .github/workflows/crilio.yml manually to enable CI gate[/]"
            )

    raise typer.Exit(0)


@app.command()
def run(
    config: str = typer.Option(
        "crilio.yaml", "--config", "-c", help="Path to crilio.yaml"
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Target model override"
    ),
    judge_model: Optional[str] = typer.Option(
        None, "--judge-model", help="Judge model override"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Show full responses"),
    json_output: bool = typer.Option(
        False, "--json", help="Machine-readable JSON output"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate config without calling APIs"
    ),
    tag: Optional[str] = typer.Option(
        None, "--tag", help="Only run tests with the specified tag."
    ),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first failure"),
):
    """Run the quality gate: Target → Judge → pass/fail."""
    t_start = time.perf_counter()

    try:
        cfg = load_config(config)
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/]")
        err_console.print("Run [bold #FF65C3]crilio init[/] to create one.")
        raise typer.Exit(2)
    except Exception as e:
        err_console.print(f"[red]Invalid config {config}: {e}[/]")
        raise typer.Exit(2)

    if tag:
        original_count = len(cfg.tests)
        cfg.tests = [test for test in cfg.tests if tag in (test.tags or [])]
        if not cfg.tests:
            console.print(
                f"[yellow]No tests found with tag '{tag}'. Running 0 tests.[/yellow]"
            )
            raise typer.Exit(0)
        console.print(
            f"[grey]Filtering by tag '{tag}': Running {len(cfg.tests)} of {original_count} tests.[/grey]"
        )

    from crilio.provider import infer_provider_from_env

    inferred = infer_provider_from_env() or "openai"
    fallback = cfg.provider or inferred or "openai"
    try:
        global_provider = resolve_provider(
            provider=cfg.provider or inferred,
            model=model or cfg.model,
            judge_model=judge_model or cfg.judge_model,
            base_url=cfg.base_url,
            api_key=None,
            fallback_provider=fallback,
        )
    except Exception as e:
        err_console.print(f"[red]Provider error: {e}[/]")
        raise typer.Exit(2)

    if dry_run:
        n_tests = len(cfg.tests)
        n_rules = sum(len(t.rules) for t in cfg.tests)
        if json_output:
            console.print_json(
                data={
                    "dry_run": True,
                    "tests": n_tests,
                    "rules": n_rules,
                    "provider": global_provider.name,
                    "model": global_provider.model,
                }
            )
        else:
            console.print(
                f"[green]✓[/] Config valid — [bold]{n_tests}[/] tests • [bold]{n_rules}[/] rules • provider=[bold #FF65C3]{global_provider.name}[/] model=[bold #FF65C3]{global_provider.model}[/]"
            )
        raise typer.Exit(0)

    if not global_provider.api_key:
        env_hint = PROVIDER_DEFAULTS[global_provider.name]["env_key"]
        key_hint = "sk-..." if global_provider.name == "openai" else "..."
        other_provider = "anthropic" if global_provider.name == "openai" else "openai"
        other_env = PROVIDER_DEFAULTS[other_provider]["env_key"]
        other_hint = "sk-..." if other_provider == "openai" else "..."
        if json_output:
            console.print_json(
                data={
                    "error": f"Missing credentials: {env_hint} not set",
                    "hint": f"export {env_hint}={key_hint} (or use {other_env}={other_hint}; add the key to .env or GitHub Secrets)",
                }
            )
        else:
            err_console.print(
                Panel(
                    f"[red]Missing credentials[/] — set {env_hint}\n\n"
                    f"  export {env_hint}={key_hint}\n"
                    f"  or export {other_env}={other_hint}\n"
                    "  [dim]Add the key to .env or GitHub Secrets[/]",
                    title="auth error",
                    border_style="red",
                )
            )
        raise typer.Exit(2)

    def _pct(spent: float, cap: float) -> str:
        p = (spent / cap * 100) if cap else 0
        s = f"{p:.2f}"
        s = s.rstrip("0").rstrip(".")
        return s

    def _budget_str(spent: float, cap: float) -> str:
        return f"${spent:.2f} / ${cap:.2f} ({_pct(spent, cap)}%)"

    budget = cfg.max_monthly_budget_usd
    n_tests = len(cfg.tests)
    n_rules = sum(len(t.rules) for t in cfg.tests)
    targets = []
    for t in cfg.tests:
        if t.target and t.target.command:
            cmd = t.target.command.strip()
            short = (
                "local: bot.py"
                if "bot.py" in cmd
                else "local: ollama"
                if "ollama" in cmd
                else f"local: {cmd.split()[0]}"
            )
            targets.append(short)
        else:
            targets.append(
                f"{t.provider or cfg.provider or global_provider.name}/{t.model or cfg.model or global_provider.model}"
            )
    uniq_targets = sorted(set(targets))
    target_str = (
        ", ".join(uniq_targets)
        if len(uniq_targets) <= 2
        else f"{uniq_targets[0]} +{len(uniq_targets) - 1} more"
    )
    if not json_output:
        console.print()
        names = ", ".join(t.name for t in cfg.tests[:3])
        if len(cfg.tests) > 3:
            names += f" +{len(cfg.tests) - 3} more"
        console.print(
            Text("crilio eval", style="bold #FF65C3")
            + Text(f"  —  {n_tests} tests ({names})", style="dim")
        )
        console.print(
            Text(f"Target  {target_str}", style="dim")
            + Text(f"  →  Judge  {global_provider.judge_model}", style="bold #FF65C3")
        )
        budget_line = Text(
            f"Budget  {_budget_str(0, budget)}" if budget is not None else "Budget  —",
            style="dim",
        )
        budget_line.append(f"  ·  {n_rules} rules", style="dim")
        console.print(budget_line)
        console.print(Rule(style="#FF65C3"))

    results: list[dict] = []
    total_pass = 0
    total_fail = 0
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    budget_exceeded = False
    stopped_early = False

    for idx, test in enumerate(cfg.tests, 1):
        if not json_output:
            console.print(Text(f"  →  Running {idx}/{len(cfg.tests)}: {test.name}...", style="dim"))
        if test.skip:
            if not json_output:
                console.print(Text(f"     {idx:02d}  {test.name}  SKIP", style="yellow"))
            continue
        is_command = bool(test.target and test.target.command)
        if is_command:
            _, judge_provider = resolve_for_test(
                global_provider=global_provider,
                test_provider=test.provider,
                test_model=test.model,
                test_judge_model=test.judge_model,
                cli_base_url=None,
                cli_api_key=None,
            )
            per_test: dict = {
                "name": test.name,
                "prompt": test.prompt,
                "provider": "command",
                "model": test.target.command[:60],
                "rules": [],
                "response": "",
                "passed": True,
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }
            try:
                target_res = call_target_command(
                    test.target.command, test.prompt, timeout=30
                )
                per_test["response"] = target_res.response
                per_test["latency_ms"] = target_res.latency_ms
                per_test["input_tokens"] += target_res.usage.input_tokens
                per_test["output_tokens"] += target_res.usage.output_tokens
                per_test["cost_usd"] += target_res.cost_usd
            except Exception as e:
                msg = str(e)
                per_test["response"] = f"[target error] {msg}"
                per_test["passed"] = False
                for rule in test.rules:
                    per_test["rules"].append(
                        {"rule": rule, "passed": False, "reasoning": msg[:200]}
                    )
                    total_fail += 1
                results.append(per_test)
                if not json_output:
                    if not per_test["passed"]:
                        for r in per_test["rules"]:
                            if not r["passed"]:
                                _post_github_pr_comment(
                                    per_test["name"],
                                    r["rule"],
                                    per_test["response"],
                                    r["reasoning"],
                                )
                if fail_fast and not per_test["passed"]:
                    if not json_output:
                        console.print(
                            f"[yellow]Fail-fast: stopping after {len(results)}/{len(cfg.tests)} tests[/]"
                        )
                    break
                continue
        else:
            tgt_provider, judge_provider = resolve_for_test(
                global_provider=global_provider,
                test_provider=test.provider,
                test_model=test.model,
                test_judge_model=test.judge_model,
                cli_base_url=None,
                cli_api_key=None,
            )
            per_test: dict = {
                "name": test.name,
                "prompt": test.prompt,
                "provider": tgt_provider.name,
                "model": tgt_provider.model,
                "rules": [],
                "response": "",
                "passed": True,
                "latency_ms": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
            }
            try:
                tgt_client = make_client(tgt_provider)
                target_res = call_target(
                    tgt_client,
                    provider=tgt_provider.name,
                    model=tgt_provider.model,
                    prompt=test.prompt,
                    system=test.system or cfg.system,
                )
                per_test["response"] = target_res.response
                per_test["latency_ms"] = target_res.latency_ms
                per_test["input_tokens"] += target_res.usage.input_tokens
                per_test["output_tokens"] += target_res.usage.output_tokens
                per_test["cost_usd"] += target_res.cost_usd
            except Exception as e:
                msg = str(e)
                is_auth = (
                    "api_key" in msg.lower()
                    or "credentials" in msg.lower()
                    or "401" in msg
                )
                if is_auth:
                    if json_output:
                        console.print_json(
                            data={
                                "error": msg,
                                "hint": f"check {PROVIDER_DEFAULTS[tgt_provider.name]['env_key']}",
                            }
                        )
                    else:
                        err_console.print(
                            Panel(msg, title="auth error", border_style="red")
                        )
                    raise typer.Exit(2)
                per_test["response"] = f"[target error] {msg}"
                per_test["passed"] = False
                for rule in test.rules:
                    per_test["rules"].append(
                        {"rule": rule, "passed": False, "reasoning": msg[:200]}
                    )
                    total_fail += 1
                results.append(per_test)
                if not json_output:
                    if not per_test["passed"]:
                        for r in per_test["rules"]:
                            if not r["passed"]:
                                _post_github_pr_comment(
                                    per_test["name"],
                                    r["rule"],
                                    per_test["response"],
                                    r["reasoning"],
                                )
                if fail_fast and not per_test["passed"]:
                    if not json_output:
                        console.print(
                            f"[yellow]Fail-fast: stopping after {len(results)}/{len(cfg.tests)} tests[/]"
                        )
                    break
                continue

        try:
            judge_client = make_client(judge_provider)
        except Exception as e:
            if json_output:
                console.print_json(data={"error": str(e)})
            else:
                err_console.print(
                    Panel(str(e), title="auth error — judge", border_style="red")
                )
            raise typer.Exit(2)

        all_pass = True
        for rule in test.rules:
            jr = judge_rule(
                judge_client,
                provider=judge_provider.name,
                judge_model=judge_provider.judge_model,
                response=target_res.response,
                rule=rule,
            )
            per_test["rules"].append(
                {"rule": jr.rule, "passed": jr.passed, "reasoning": jr.reasoning}
            )
            per_test["input_tokens"] += jr.usage.input_tokens
            per_test["output_tokens"] += jr.usage.output_tokens
            per_test["cost_usd"] += jr.cost_usd
            if jr.passed:
                total_pass += 1
            else:
                total_fail += 1
                all_pass = False
        per_test["passed"] = all_pass
        results.append(per_test)
        total_cost += per_test["cost_usd"]
        total_input_tokens += per_test["input_tokens"]
        total_output_tokens += per_test["output_tokens"]
        if not json_output and not per_test["passed"]:
            for r in per_test["rules"]:
                if not r["passed"]:
                    _post_github_pr_comment(
                        per_test["name"],
                        r["rule"],
                        per_test["response"],
                        r["reasoning"],
                    )
        if fail_fast and not per_test["passed"]:
            if not json_output:
                console.print(
                    f"[yellow]Fail-fast: stopping after {len(results)}/{len(cfg.tests)} tests[/]"
                )
            break
        if budget is not None and total_cost > budget:
            budget_exceeded = True
            stopped_early = True
            if not json_output:
                console.print(
                    f"[red]Budget exceeded: {_budget_str(total_cost, budget)} — stopping. {len(cfg.tests) - idx} test(s) skipped.[/]"
                )
            break

    elapsed = time.perf_counter() - t_start
    gate_passed = total_fail == 0
    if budget is not None and total_cost > budget:
        budget_exceeded = True

    if not json_output and results:
        from rich.box import ROUNDED

        eval_tbl = Table(
            show_header=True,
            header_style="bold #FF65C3",
            box=ROUNDED,
            padding=(0, 1),
            show_lines=True,
        )
        eval_tbl.add_column("Test", style="bold white", no_wrap=True)
        eval_tbl.add_column(
            "Prompt", style="dim", ratio=1, min_width=24, overflow="fold"
        )
        eval_tbl.add_column(
            "Output", style="white", ratio=1, min_width=24, overflow="fold"
        )
        eval_tbl.add_column("Verdict", justify="center", no_wrap=True, width=7)
        for r in results:
            passed = r["passed"]
            verdict = (
                Text("PASS", style="green")
                if passed
                else Text("FAIL", style="red bold")
            )
            prompt = r["prompt"].replace("\n", " ")
            output = r["response"].replace("\n", " ")
            eval_tbl.add_row(
                Text(r["name"][:22], style="white"),
                Text(prompt, style="dim"),
                Text(output, style="white"),
                verdict,
            )
        console.print(eval_tbl)
        console.print()

    gate_passed = gate_passed and not budget_exceeded
    payload = {
        "gate": "PASS" if gate_passed else "FAIL",
        "elapsed_s": round(elapsed, 2),
        "summary": {
            "passed": total_pass,
            "failed": total_fail,
            "total": total_pass + total_fail,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cost_usd": round(total_cost, 6),
            "max_monthly_budget_usd": budget,
            "budget_exceeded": budget_exceeded,
            "stopped_early": stopped_early,
        },
        "tests": results,
    }
    if not dry_run:
        try:
            from crilio.history import save_run

            save_run(payload)
        except Exception:
            pass
    if json_output:
        console.print_json(data=payload)
    else:
        _render_summary(gate_passed, total_pass, total_fail, elapsed, budget_exceeded)
        cost_line = Text(f"Cost  ${total_cost:.4f}", style="dim")
        cost_line.append(
            f"  ·  {total_input_tokens + total_output_tokens:,} tokens", style="dim"
        )
        if budget is not None and total_cost > 0:
            cost_line.append(
                f"  ·  Budget {_budget_str(total_cost, budget)}", style="dim"
            )
        if stopped_early:
            cost_line.append(
                f"  ·  Stopped early {len(results)}/{len(cfg.tests)}", style="yellow"
            )
        console.print(cost_line)

    if _is_pr():
        raise typer.Exit(0 if gate_passed else 1)
    raise typer.Exit(0)


@app.command()
def validate(
    config: str = typer.Option(
        "crilio.yaml", "--config", "-c", help="Path to crilio.yaml"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Machine-readable JSON output"
    ),
):
    """Validate configuration without calling provider APIs."""
    try:
        cfg = load_config(config)
        provider = resolve_provider(
            provider=cfg.provider,
            model=cfg.model,
            judge_model=cfg.judge_model,
            base_url=cfg.base_url,
        )
    except FileNotFoundError as error:
        message = str(error)
        if json_output:
            console.print_json(data={"valid": False, "error": message})
        else:
            err_console.print(f"[red]✗ {message}[/]")
            err_console.print("Run [bold #FF65C3]crilio init[/] to create one.")
        raise typer.Exit(2)
    except Exception as error:
        message = str(error)
        if json_output:
            console.print_json(data={"valid": False, "error": message})
        else:
            err_console.print(f"[red]✗ Configuration invalid[/]\n\n  {message}")
        raise typer.Exit(2)

    n_tests = len(cfg.tests)
    n_rules = sum(len(test.rules) for test in cfg.tests)
    budget = cfg.max_monthly_budget_usd
    result = {
        "valid": True,
        "config": config,
        "provider": provider.name,
        "model": provider.model,
        "judge_model": provider.judge_model,
        "tests": n_tests,
        "rules": n_rules,
        "max_monthly_budget_usd": budget,
    }
    if json_output:
        console.print_json(data=result)
    else:
        budget_text = f"${budget:.2f}" if budget is not None else "not configured"
        console.print("[green]✓ Configuration valid[/]")
        console.print(f"  Provider: {provider.name}")
        console.print(f"  Target model: {provider.model}")
        console.print(f"  Judge model: {provider.judge_model}")
        console.print(f"  Tests: {n_tests}")
        console.print(f"  Rules: {n_rules}")
        console.print(f"  Budget: {budget_text}")
        if budget is not None:
            console.print(f"  Remaining on fresh run: ${budget:.2f}")
        console.print(Text("Tip: crilio run --dry-run  ·  crilio ls", style="dim"))
    raise typer.Exit(0)


@app.command("ls")
@app.command("list", hidden=True)
def list_tests(
    config: str = typer.Option(
        "crilio.yaml", "--config", "-c", help="Path to crilio.yaml"
    ),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON"),
):
    """List tests in crilio.yaml."""
    try:
        cfg = load_config(config)
    except Exception as e:
        err_console.print(f"[red]Invalid config {config}: {e}[/]")
        raise typer.Exit(2)
    tests = cfg.tests
    if tag:
        tests = [t for t in tests if tag in (t.tags or [])]
    if json_output:
        console.print_json(
            data=[
                {
                    "name": t.name,
                    "tags": t.tags or [],
                    "skip": t.skip,
                    "rules": len(t.rules),
                    "target": t.target.command
                    if t.target
                    else f"{t.provider or cfg.provider}/{t.model or cfg.model}",
                }
                for t in tests
            ]
        )
        raise typer.Exit(0)

    c = console
    n_total = len(cfg.tests)
    c.print()
    c.print(
        f"[bold #FF65C3]crilio[/]  ·  [bold]{len(tests)} test{'s' if len(tests) != 1 else ''}[/] in {config}"
    )
    c.print("[dim]" + "─" * (c.width if c.width else 80) + "[/]")
    c.print()

    tbl = Table(show_header=True, header_style="#FF65C3", box=None, padding=(0, 2))
    tbl.add_column("#", width=3, style="#FF65C3")
    tbl.add_column("Test", ratio=1, style="white")
    tbl.add_column("Tags", ratio=1, style="#FF65C3")
    tbl.add_column("Rules", width=6, justify="center", style="yellow")
    tbl.add_column("Target", ratio=1, style="dim")
    for idx, t in enumerate(tests, 1):
        tags = ", ".join(t.tags or []) or "[dim]—[/]"
        target = (
            t.target.command[:40] + "…"
            if t.target and len(t.target.command) > 40
            else (
                t.target.command
                if t.target
                else f"{t.provider or cfg.provider or 'openai'}/{t.model or cfg.model or 'gpt-4o-mini'}"
            )
        )
        name = t.name
        if t.skip:
            name = f"{name} [yellow](skipped)[/]"
        tbl.add_row(str(idx), name, tags, str(len(t.rules)), target)
    c.print(tbl)
    c.print()
    c.print(f"[dim]{len(tests)}/{n_total} tests shown[/]")
    if len(tests) > 1 and not tag:
        c.print(
            Text(
                "Tip: crilio run --tag <tag>  ·  crilio ls --tag smoke --json",
                style="dim",
            )
        )
    raise typer.Exit(0)


@app.command()
def diff(
    base: str = typer.Option("main", "--base", "-b", help="Base git ref"),
    config: str = typer.Option(
        "crilio.yaml", "--config", "-c", help="Path to crilio.yaml"
    ),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON"),
    fail_on_change: bool = typer.Option(
        False, "--fail-on-change", help="Exit 1 if changes"
    ),
):
    """Show prompt/rule diff between git refs."""

    def _load_ref(ref: str):
        try:
            r = subprocess.run(
                ["git", "show", f"{ref}:{config}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                return yaml.safe_load(r.stdout) or {}
        except Exception:
            pass
        return None

    def _load_cur():
        try:
            return (
                yaml.safe_load(pathlib.Path(config).read_text(encoding="utf-8")) or {}
            )
        except Exception as e:
            err_console.print(f"[red]Invalid config {config}: {e}[/]")
            raise typer.Exit(2)

    cur = _load_cur()
    base_data = _load_ref(base)
    if base_data is None:
        for alt in ["origin/main", "HEAD~1", "HEAD"]:
            if alt == base:
                continue
            base_data = _load_ref(alt)
            if base_data is not None:
                base = alt
                break
        if base_data is None:
            err_console.print(f"[yellow]No base {base} found — showing current only[/]")
            base_data = {"tests": []}

    def _map(d):
        m = {}
        for t in d.get("tests") or []:
            m[t.get("name")] = t
        return m

    bmap, cmap = _map(base_data), _map(cur)
    changes = []
    for name in sorted(set(list(bmap.keys()) + list(cmap.keys()))):
        b, c = bmap.get(name), cmap.get(name)
        if b is None:
            changes.append({"test": name, "field": "test", "change": "added"})
        elif c is None:
            changes.append({"test": name, "field": "test", "change": "removed"})
        else:
            for f in [
                "prompt",
                "rules",
                "tags",
                "target",
                "system",
                "provider",
                "model",
            ]:
                if b.get(f) != c.get(f):
                    changes.append(
                        {
                            "test": name,
                            "field": f,
                            "before": b.get(f),
                            "after": c.get(f),
                        }
                    )
    if json_output:
        console.print_json(
            data={
                "base": base,
                "config": config,
                "changes": changes,
                "count": len(changes),
            }
        )
        raise typer.Exit(1 if fail_on_change and changes else 0)
    if not changes:
        console.print(f"[green]No changes[/] — {base} → HEAD ({len(cmap)} tests)")
        raise typer.Exit(0)
    tbl = Table(show_header=True, header_style="dim", box=None, padding=(0, 1))
    tbl.add_column("Test", style="#FF65C3", no_wrap=True)
    tbl.add_column("Field", style="yellow", no_wrap=True)
    tbl.add_column("Change", ratio=1)
    display_rows = 0
    for ch in sorted(changes, key=lambda x: (x["test"], x["field"])):
        if ch.get("change") in ("added", "removed"):
            tbl.add_row(ch["test"], ch["field"], f"[bold]{ch['change']}[/]")
            display_rows += 1
        else:
            if (
                ch["field"] in ("rules", "tags")
                and isinstance(ch["before"], list)
                and isinstance(ch["after"], list)
            ):
                b_set, c_set = set(ch["before"] or []), set(ch["after"] or [])
                for added in sorted(c_set - b_set):
                    tbl.add_row(ch["test"], ch["field"], f"[green]+ {added}[/]")
                    display_rows += 1
                for removed in sorted(b_set - c_set):
                    tbl.add_row(ch["test"], ch["field"], f"[red]- {removed}[/]")
                    display_rows += 1
            else:
                before = (
                    str(ch["before"])[:120].replace("\n", " ")
                    if ch["before"] is not None
                    else "[dim]—[/]"
                )
                after = (
                    str(ch["after"])[:120].replace("\n", " ")
                    if ch["after"] is not None
                    else "[dim]—[/]"
                )
                tbl.add_row(
                    ch["test"], ch["field"], f"[red]- {before}[/]\n[green]+ {after}[/]"
                )
                display_rows += 1
    console.print(
        Panel(
            tbl,
            title=f"[bold #FF65C3]Diff: {base} → HEAD[/]",
            border_style="#FF65C3",
            padding=(0, 1),
        )
    )
    word = "change" if display_rows == 1 else "changes"
    console.print(f"[dim]{display_rows} {word} — {base} → HEAD ({len(cmap)} tests)[/]")
    if changes and not json_output:
        console.print(
            Text("Tip: crilio run --fail-fast  ·  crilio ls --tag <tag>", style="dim")
        )
    raise typer.Exit(1 if fail_on_change and changes else 0)


def _render_test_simple(
    idx: int, test: dict, budget: float | None = None, spent: float = 0
):
    status = "PASS" if test["passed"] else "FAIL"
    style = "green" if test["passed"] else "red"
    badge = Text(f" {status} ", style=f"bold {style} reverse")
    cost = test.get("cost_usd", 0)
    num = f"{idx:02d}"
    console.print()
    line = Text()
    line.append(f"{num}", style="dim")
    line.append(f"  {test['name']}  ", style="bold white")
    line.append(badge)
    console.print(line)
    if not test["passed"]:
        for r in test["rules"]:
            if not r["passed"]:
                console.print(
                    Text(f"   → {r.get('reasoning', '')[:140]}", style="yellow")
                )
                break
    meta = Text(
        f"   {test['provider']}/{test['model']}  {test['latency_ms']}ms  ${cost:.4f}",
        style="dim",
    )
    if budget is not None:
        pct = (spent / budget * 100) if budget else 0
        pct_s = f"{pct:.0f}"
        meta.append(f"  ·  Budget {pct_s}%", style="dim")
    console.print(meta)


def _render_test(console: Console, test: dict, verbose: bool):
    resp = test["response"] or "[empty]"
    preview = resp if verbose else (resp[:320] + ("…" if len(resp) > 320 else ""))
    prompt = test.get("prompt", "")
    if prompt and prompt.strip() != resp.strip():
        console.print(Text(f"   prompt: {prompt[:100]}", style="dim"))
        console.print()
    console.print(
        Panel(
            preview,
            title="[dim]output[/]",
            border_style="dim",
            padding=(0, 1),
            width=min(78, console.width - 8),
        )
    )
    tbl = Table(show_header=False, box=None, padding=(0, 1), show_lines=False)
    tbl.add_column("", width=2, no_wrap=True)
    tbl.add_column("Rule", ratio=1, min_width=20)
    tbl.add_column("Verdict", width=7, justify="center", no_wrap=True)
    for r in test["rules"]:
        icon = Text("●", style="green" if r["passed"] else "red")
        verdict = (
            Text("PASS", style="green")
            if r["passed"]
            else Text("FAIL", style="red bold")
        )
        tbl.add_row(icon, r["rule"], verdict)
    console.print(tbl)


def _is_pr() -> bool:
    if os.getenv("GITHUB_EVENT_NAME") == "pull_request":
        return True
    ref = os.getenv("GITHUB_REF", "")
    if ref.startswith("refs/pull/"):
        return True
    return False


@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of runs to show"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON"),
):
    """Show recent runs from .crilio/history.jsonl."""
    from crilio.history import load_history

    records = load_history(limit=limit)
    if json_output:
        console.print_json(data=records)
        raise typer.Exit(0)
    if not records:
        console.print("[dim]No history — run [bold #FF65C3]crilio run[/] first[/]")
        raise typer.Exit(0)
    tbl = Table(show_header=True, header_style="bold #FF65C3", box=None, padding=(0, 1))
    tbl.add_column("Executed", style="dim", no_wrap=True)
    tbl.add_column("Gate", justify="center", width=6)
    tbl.add_column("Pass/Fail", justify="center")
    tbl.add_column("Took", justify="right", style="dim")
    tbl.add_column("Cost", justify="right", style="dim")
    tbl.add_column("SHA", style="dim", no_wrap=True)
    tbl.add_column("Branch", style="dim")
    for r in records:
        gate = r.get("gate", "?")
        style = "green" if gate == "PASS" else "red bold" if gate == "FAIL" else "dim"
        s = r.get("summary", {})
        took = f"{r.get('elapsed_s', 0):.1f}s" if r.get("elapsed_s") is not None else "-"
        ts = (r.get("timestamp") or "")[:19].replace("T", " ")
        tbl.add_row(
            ts,
            Text(gate, style=style),
            f"{s.get('passed',0)}/{s.get('total',0)}",
            took,
            f"${s.get('cost_usd',0):.4f}",
            (r.get("git_sha") or "-")[:7],
            r.get("git_branch") or "-",
        )
    console.print(tbl)
    console.print(f"[dim]{len(records)} run(s) — .crilio/history.jsonl[/]")
    raise typer.Exit(0)


@app.command()
def report(
    fmt: str = typer.Option("html", "--format", "-f", help="html or junit"),
    output: str = typer.Option(None, "--output", "-o", help="Output path"),
    json_output: bool = typer.Option(False, "--json", help="Print payload instead of writing file"),
):
    """Generate HTML or JUnit report from last run."""
    from crilio.history import load_last_payload
    from crilio.report import write_report

    payload = load_last_payload()
    if payload is None:
        err_console.print("[red]No history — run [bold #FF65C3]crilio run[/] first[/]")
        raise typer.Exit(2)
    if fmt not in ("html", "junit"):
        err_console.print("[red]--format must be html or junit[/]")
        raise typer.Exit(2)
    if json_output:
        console.print_json(data=payload)
        raise typer.Exit(0)
    default = "crilio-report.html" if fmt == "html" else "crilio-junit.xml"
    out = pathlib.Path(output or default)
    write_report(payload, fmt, out)
    console.print(f"[green]✓ Report written to {out}[/] — gate={payload.get('gate')} {payload.get('summary',{}).get('passed',0)}/{payload.get('summary',{}).get('total',0)}")
    raise typer.Exit(0)


def _render_summary(
    passed: bool, ok: int, fail: int, elapsed: float, budget_exceeded: bool = False
):
    total = ok + fail
    console.print(Rule(style="#FF65C3"))
    if passed:
        label = Text(
            f"Gate  PASS  —  {ok}/{total} rules  ·  {elapsed:.1f}s",
            style="bold #FF65C3",
        )
        label.append(
            "  ·  Local run — not blocking"
            if not _is_pr()
            else "  ·  ✓ PR can be merged",
            style="dim",
        )
        console.print(label)
    else:
        reason = (
            "budget exceeded"
            if budget_exceeded and fail == 0
            else f"{fail}/{total} FAILED"
        )
        label = Text(f"Gate  FAIL  —  {reason}  ·  {elapsed:.1f}s", style="bold red")
        label.append(
            "  ·  Local run — not blocking" if not _is_pr() else "  ·  ✗ blocking PR",
            style="dim",
        )
        console.print(label)


if __name__ == "__main__":
    app()

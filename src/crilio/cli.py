from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Optional

import requests

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from crilio.__version__ import __version__
from crilio.config import DEFAULT_CONFIG_YAML, CrilioConfig, load_config
from crilio.judge import judge_rule
from crilio.provider import PROVIDER_DEFAULTS, VALID_PROVIDERS, load_dotenv, make_client, resolve_for_test, resolve_provider
from crilio.target import call_target, call_target_command

app = typer.Typer(name="crilio", add_completion=False, no_args_is_help=False)
console = Console()
err_console = Console(stderr=True)

CRILIO_ASCII = r""" ____ ____  ___ _     ___ ___
/ ___|  _ \|_ _| |   |_ _/ _ \
| |   | |_) || || |    | | | | |
| |___|  _ < | || |___ | | |_| |
\____|_| \_\___|_____|___\___/"""


def _show_homepage():
    w = console.width if console.width else 80
    c = console
    c.print()
    if w >= 64:
        from rich.text import Text

        c.print(Panel(Text(CRILIO_ASCII, style="bold white", justify="center"), border_style="white", padding=(1, 2)))
        c.print(Text("The CI/CD Quality Gate for AI  —  pytest for prompts", style="dim", justify="center"))
        c.print(Text("Stop shipping prompt regressions to production", style="bold dim", justify="center"))
        c.print()
    else:
        c.print(Panel.fit("  Crilio  —  pytest for prompts  ", style="bold white", border_style="white", padding=(1, 2)))
        c.print()
    c.print(Panel.fit("  pip install crilio  →  crilio init  →  set a provider key  →  crilio run  ", border_style="cyan", padding=(1, 2)))
    c.print()
    tbl = Table(show_header=False, box=None, padding=(0, 2))
    tbl.add_column("cmd", style="cyan", no_wrap=True, min_width=18)
    tbl.add_column("desc", style="dim")
    tbl.add_row("crilio init", "Create crilio.yaml (Step 3) + optionally .github/workflows/crilio.yml")
    tbl.add_row("crilio run", "Gate: Target (gpt-4o) → Judge (gpt-4o-mini) → ✅/❌ report → exit 1 blocks PR (if GHA)")
    tbl.add_row("crilio --docs", "Full guide — concept, config, providers, rules, CI")
    tbl.add_row("crilio --version", "Show version")
    c.print(tbl)
    c.print()
    n_tests = 0
    n_rules = 0
    provider = "openai"
    model = "gpt-4o"
    try:
        from crilio.config import load_config

        cfg = load_config("crilio.yaml")
        n_tests = len(cfg.tests)
        n_rules = sum(len(t.rules) for t in cfg.tests)
        provider = cfg.provider or "openai"
        model = cfg.model or "gpt-4o"
        c.print(Panel(f"  [green]● crilio.yaml found[/]  [dim]{n_tests} tests · {n_rules} rules · {provider}/{model}[/]  [cyan]crilio run --dry-run[/] to validate  ", border_style="green", padding=(0, 2)))
    except Exception:
        c.print(Panel("  [yellow]● No crilio.yaml[/]  [dim]Run [cyan]crilio init[/] to create one → set OPENAI_API_KEY or ANTHROPIC_API_KEY → [cyan]crilio run[/][/]", border_style="yellow", padding=(0, 2)))
    c.print()
    configured_key = next(
        ((name, defaults["env_key"], os.getenv(defaults["env_key"], "")) for name, defaults in PROVIDER_DEFAULTS.items() if os.getenv(defaults["env_key"])),
        None,
    )
    if configured_key:
        from crilio.setup import mask_key

        name, env_key, key = configured_key
        c.print(f"[dim]  {name}/{env_key}: {mask_key(key)} [green]● detected[/][/]")
    else:
        c.print("[dim]  Provider key: [red]○ missing[/] → set OPENAI_API_KEY or ANTHROPIC_API_KEY (.env / GitHub Secrets)[/]")
    c.print()


def _post_github_pr_comment(test_name: str, rule_broken: str, ai_response: str, reason: str):
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
        "Accept": "application/vnd.github.v3+json"
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
    version: bool = typer.Option(None, "--version", "-v", help="Show version", callback=version_callback, is_eager=True),
    docs: bool = typer.Option(None, "--docs", help="Show full documentation guide", callback=docs_callback, is_eager=True, hidden=True),
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
):
    """Initialize crilio.yaml — Step 3 of setup."""
    dest = pathlib.Path("crilio.yaml")
    if dest.exists() and not force:
        err_console.print(f"[yellow]crilio.yaml already exists at {dest} — use --force to overwrite[/]")
        raise typer.Exit(1)
    from crilio.config import dump_yaml
    import yaml as _yaml

    cfg = CrilioConfig.model_validate(_yaml.safe_load(DEFAULT_CONFIG_YAML))
    if dest.exists() and force:
        dest.unlink()
    dest.write_text(dump_yaml(cfg), encoding="utf-8")
    console.print(f"[green]✓ Created {dest}[/] — {len(cfg.tests)} tests")
    console.print()
    console.print(Panel.fit("  [yellow]⚠  Please check and modify [cyan]crilio.yaml[/] according to your need[/]\n  [dim]Update prompts and rules to match your app, then run [cyan]crilio run[/][/]", border_style="yellow", padding=(0, 2)))
    console.print()
    console.print("[dim]Next: set [cyan]OPENAI_API_KEY[/] or [cyan]ANTHROPIC_API_KEY[/] → [cyan]crilio run --dry-run[/] → [cyan]crilio run[/][/]")

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

            if Confirm.ask("Do you want to automatically setup GitHub Actions to run on every Pull Request?", default=False, console=console):
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

                        should_overwrite = Confirm.ask(f"{wf_path} already exists — replace it?", default=False, console=console)
                    except Exception:
                        should_overwrite = False
                if should_overwrite:
                    wf_path.write_text(wf_content, encoding="utf-8")
                    console.print(f"[green]✓ Created {wf_path}[/] — runs on every Pull Request")
                else:
                    console.print(f"[yellow]Kept existing {wf_path} — not overwritten[/]")
        else:
            wf_path.write_text(wf_content, encoding="utf-8")
            console.print(f"[green]✓ Created {wf_path}[/] — runs on every Pull Request")
    else:
        if is_tty and not yes:
            console.print("[dim]Skipped GitHub Actions setup — create .github/workflows/crilio.yml manually to enable CI gate[/]")

    raise typer.Exit(0)


@app.command()
def run(
    config: str = typer.Option("crilio.yaml", "--config", "-c", help="Path to crilio.yaml"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Target model override"),
    judge_model: Optional[str] = typer.Option(None, "--judge-model", help="Judge model override"),
    verbose: bool = typer.Option(False, "--verbose", help="Show full responses"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate config without calling APIs"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Only run tests with the specified tag."),
):
    """Run the quality gate: Target → Judge → pass/fail."""
    t_start = time.perf_counter()

    try:
        cfg = load_config(config)
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/]")
        err_console.print("Run [cyan]crilio init[/] to create one.")
        raise typer.Exit(2)
    except Exception as e:
        err_console.print(f"[red]Invalid config {config}: {e}[/]")
        raise typer.Exit(2)

    if tag:
        original_count = len(cfg.tests)
        cfg.tests = [test for test in cfg.tests if tag in (test.tags or [])]
        if not cfg.tests:
            console.print(f"[yellow]No tests found with tag '{tag}'. Running 0 tests.[/yellow]")
            raise typer.Exit(0)
        console.print(f"[grey]Filtering by tag '{tag}': Running {len(cfg.tests)} of {original_count} tests.[/grey]")

    from crilio.provider import infer_provider_from_env

    inferred = infer_provider_from_env() or "openai"
    fallback = cfg.provider or inferred or "openai"
    try:
        global_provider = resolve_provider(
            provider=cfg.provider or inferred,
            model=model or cfg.model,
            judge_model=judge_model or cfg.judge_model,
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
            console.print_json(data={"dry_run": True, "tests": n_tests, "rules": n_rules, "provider": global_provider.name, "model": global_provider.model})
        else:
            console.print(f"[green]✓[/] Config valid — [bold]{n_tests}[/] tests • [bold]{n_rules}[/] rules • provider=[cyan]{global_provider.name}[/] model=[cyan]{global_provider.model}[/]")
        raise typer.Exit(0)

    if not global_provider.api_key:
        env_hint = PROVIDER_DEFAULTS[global_provider.name]["env_key"]
        key_hint = "sk-..." if global_provider.name == "openai" else "..."
        other_provider = "anthropic" if global_provider.name == "openai" else "openai"
        other_env = PROVIDER_DEFAULTS[other_provider]["env_key"]
        other_hint = "sk-..." if other_provider == "openai" else "..."
        if json_output:
            console.print_json(data={
                "error": f"Missing credentials: {env_hint} not set",
                "hint": f"export {env_hint}={key_hint} (or use {other_env}={other_hint}; add the key to .env or GitHub Secrets)",
            })
        else:
            err_console.print(Panel(
                f"[red]Missing credentials[/] — set {env_hint}\n\n"
                f"  export {env_hint}={key_hint}\n"
                f"  or export {other_env}={other_hint}\n"
                "  [dim]Add the key to .env or GitHub Secrets[/]",
                title="auth error",
                border_style="red",
            ))
        raise typer.Exit(2)

    def _pct(spent: float, cap: float) -> str:
        p = (spent / cap * 100) if cap else 0
        s = f"{p:.2f}"
        s = s.rstrip("0").rstrip(".")
        return s

    def _budget_str(spent: float, cap: float) -> str:
        return f"${spent:.2f} / ${cap:.2f} ({_pct(spent, cap)}%)"

    budget = cfg.max_monthly_budget_usd
    console.print("[bold]🧪 Crilio Test Runner[/]")
    if budget is not None:
        console.print(f"Budget: {_budget_str(0, budget)}")
    console.print(f"[dim]Found {len(cfg.tests)} test(s)...[/]")
    console.print()

    if not json_output:
        console.print(Panel.fit(f"[bold]Crilio gate[/] • {len(cfg.tests)} tests • {sum(len(t.rules) for t in cfg.tests)} rules • [cyan]{global_provider.name}[/]/[cyan]{global_provider.model}[/] → judge [cyan]{global_provider.judge_model}[/]", border_style="dim"))

    results: list[dict] = []
    total_pass = 0
    total_fail = 0
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    budget_exceeded = False
    stopped_early = False

    for idx, test in enumerate(cfg.tests, 1):
        if test.skip:
            if not json_output:
                console.print(f"[dim]Test {idx}: {test.name} [yellow]SKIPPED[/] — skip: true[/]")
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
                target_res = call_target_command(test.target.command, test.prompt, timeout=30)
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
                    per_test["rules"].append({"rule": rule, "passed": False, "reasoning": msg[:200]})
                    total_fail += 1
                results.append(per_test)
                if not json_output:
                    _render_test_simple(idx, per_test, budget, total_cost)
                    _render_test(console, per_test, verbose)
                    if not per_test["passed"]:
                        for r in per_test["rules"]:
                            if not r["passed"]:
                                _post_github_pr_comment(per_test["name"], r["rule"], per_test["response"], r["reasoning"])
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
                target_res = call_target(tgt_client, provider=tgt_provider.name, model=tgt_provider.model, prompt=test.prompt, system=test.system or cfg.system)
                per_test["response"] = target_res.response
                per_test["latency_ms"] = target_res.latency_ms
                per_test["input_tokens"] += target_res.usage.input_tokens
                per_test["output_tokens"] += target_res.usage.output_tokens
                per_test["cost_usd"] += target_res.cost_usd
            except Exception as e:
                msg = str(e)
                is_auth = "api_key" in msg.lower() or "credentials" in msg.lower() or "401" in msg
                if is_auth:
                    if json_output:
                        console.print_json(data={"error": msg, "hint": f"check {PROVIDER_DEFAULTS[tgt_provider.name]['env_key']}"})
                    else:
                        err_console.print(Panel(msg, title="auth error", border_style="red"))
                    raise typer.Exit(2)
                per_test["response"] = f"[target error] {msg}"
                per_test["passed"] = False
                for rule in test.rules:
                    per_test["rules"].append({"rule": rule, "passed": False, "reasoning": msg[:200]})
                    total_fail += 1
                results.append(per_test)
                if not json_output:
                    _render_test_simple(idx, per_test, budget, total_cost)
                    _render_test(console, per_test, verbose)
                    if not per_test["passed"]:
                        for r in per_test["rules"]:
                            if not r["passed"]:
                                _post_github_pr_comment(per_test["name"], r["rule"], per_test["response"], r["reasoning"])
                continue

        try:
            judge_client = make_client(judge_provider)
        except Exception as e:
            if json_output:
                console.print_json(data={"error": str(e)})
            else:
                err_console.print(Panel(str(e), title="auth error — judge", border_style="red"))
            raise typer.Exit(2)

        all_pass = True
        for rule in test.rules:
            jr = judge_rule(judge_client, provider=judge_provider.name, judge_model=judge_provider.judge_model, response=target_res.response, rule=rule)
            per_test["rules"].append({"rule": jr.rule, "passed": jr.passed, "reasoning": jr.reasoning})
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
        if not json_output:
            _render_test_simple(idx, per_test, budget, total_cost)
            _render_test(console, per_test, verbose)
            if not per_test["passed"]:
                for r in per_test["rules"]:
                    if not r["passed"]:
                        _post_github_pr_comment(per_test["name"], r["rule"], per_test["response"], r["reasoning"])
        if budget is not None and total_cost > budget:
            budget_exceeded = True
            stopped_early = True
            if not json_output:
                console.print(f"[red]Budget exceeded: {_budget_str(total_cost, budget)} — stopping. {len(cfg.tests)-idx} test(s) skipped.[/]")
            break

    elapsed = time.perf_counter() - t_start
    gate_passed = total_fail == 0
    if budget is not None and total_cost > budget:
        budget_exceeded = True

    if json_output:
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
        console.print_json(data=payload)
    else:
        gate_passed = gate_passed and not budget_exceeded
        _render_summary(gate_passed, total_pass, total_fail, elapsed, budget_exceeded)
        if budget is not None:
            console.print(f"Final Budget: {_budget_str(total_cost, budget)}")
            remaining = max(0, budget - total_cost)
            console.print(f"Remaining: ${remaining:.2f}")
            if stopped_early:
                console.print(f"[yellow]Stopped early — budget exceeded after {len(results)}/{len(cfg.tests)} tests[/]")
        else:
            console.print(
                f"[dim]Usage: {total_input_tokens + total_output_tokens:,} tokens • "
                f"estimated cost ${total_cost:.6f}[/]"
            )

    gha_enabled = pathlib.Path(".github/workflows/crilio.yml").exists() or os.getenv("GITHUB_ACTIONS") == "true"
    if not gha_enabled:
        if not gate_passed:
            console.print("[yellow]Note: Gate failed locally — not blocking (GitHub Actions not enabled). Enable via crilio init → Yes to GitHub Actions[/]")
        raise typer.Exit(0)
    raise typer.Exit(0 if gate_passed else 1)


@app.command()
def validate(
    config: str = typer.Option("crilio.yaml", "--config", "-c", help="Path to crilio.yaml"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
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
            err_console.print("Run [cyan]crilio init[/] to create one.")
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
    raise typer.Exit(0)


@app.command("ls")
@app.command("list", hidden=True)
def list_tests(
    config: str = typer.Option("crilio.yaml", "--config", "-c", help="Path to crilio.yaml"),
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
        console.print_json(data=[{"name": t.name, "tags": t.tags or [], "skip": t.skip, "rules": len(t.rules), "target": t.target.command if t.target else f"{t.provider or cfg.provider}/{t.model or cfg.model}"} for t in tests])
        raise typer.Exit(0)
    tbl = Table(show_header=True, header_style="dim", box=None, padding=(0, 1))
    tbl.add_column("#", width=3)
    tbl.add_column("Test", ratio=1)
    tbl.add_column("Tags", ratio=1)
    tbl.add_column("Rules", width=6, justify="center")
    tbl.add_column("Target", ratio=1)
    for idx, t in enumerate(tests, 1):
        status = " [yellow]skip[/]" if t.skip else ""
        tags = ", ".join(t.tags or []) or "[dim]—[/]"
        target = t.target.command[:40] + "…" if t.target and len(t.target.command) > 40 else (t.target.command if t.target else f"{t.provider or cfg.provider or 'openai'}/{t.model or cfg.model or 'gpt-4o-mini'}")
        tbl.add_row(str(idx), f"{t.name}{status}", tags, str(len(t.rules)), target)
    console.print(tbl)
    console.print(f"[dim]{len(tests)}/{len(cfg.tests)} tests shown[/]")
    raise typer.Exit(0)


def _render_test_simple(idx: int, test: dict, budget: float | None = None, spent: float = 0):
    status = "✅" if test["passed"] else "❌"
    cost = test.get("cost_usd", 0)
    console.print(f"\n[bold]Test {idx}: {test['name']} {status} (${cost:.2f})[/]")
    if not test["passed"]:
        for r in test["rules"]:
            if not r["passed"]:
                console.print(f"   Reason: {r.get('reasoning','')[:200]}")
                break
    else:
        console.print(f"   Reason: All {len(test['rules'])} rules passed")
    console.print(f"   [dim]{test['provider']}/{test['model']} • {test['latency_ms']}ms[/]")
    if budget is not None:
        pct = (spent / budget * 100) if budget else 0
        pct_s = f"{pct:.2f}".rstrip("0").rstrip(".")
        console.print(f"   → Budget: ${spent:.2f} / ${budget:.2f} ({pct_s}%)")


def _render_test(console: Console, test: dict, verbose: bool):
    resp = test["response"] or "[empty]"
    preview = resp if verbose else (resp[:480] + ("…" if len(resp) > 480 else ""))
    console.print(Panel(preview, title="response", border_style="dim", padding=(0, 1)))
    tbl = Table(show_header=True, header_style="dim", box=None, padding=(0, 1))
    tbl.add_column("", width=2)
    tbl.add_column("Rule", ratio=1)
    tbl.add_column("Verdict", width=8, justify="center")
    tbl.add_column("Reason", ratio=1, style="dim")
    for r in test["rules"]:
        icon = Text("●", style="green" if r["passed"] else "red")
        verdict = Text("PASS", style="green") if r["passed"] else Text("FAIL", style="red bold")
        tbl.add_row(icon, r["rule"], verdict, r.get("reasoning", "")[:120])
    console.print(tbl)


def _render_summary(passed: bool, ok: int, fail: int, elapsed: float, budget_exceeded: bool = False):
    total = ok + fail
    if passed:
        console.print(f"\n[green bold]✓ Gate passed[/] — {ok}/{total} rules • {elapsed:.1f}s")
    else:
        reason = "budget exceeded" if budget_exceeded and fail == 0 else f"{fail}/{total} FAILED"
        console.print(f"\n[red bold]✗ Gate failed[/] — {reason} • {elapsed:.1f}s")
        if pathlib.Path(".github/workflows/crilio.yml").exists() or os.getenv("GITHUB_ACTIONS") == "true":
            console.print("[dim]blocking PR[/]")


if __name__ == "__main__":
    app()

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from crilio.__version__ import __version__
from crilio.config import DEFAULT_CONFIG_YAML, CrilioConfig, load_config
from crilio.judge import judge_rule
from crilio.provider import PROVIDER_DEFAULTS, VALID_PROVIDERS, load_dotenv, make_client, resolve_for_test, resolve_provider
from crilio.target import call_target

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
        with:
          python-version: '3.10'
      - run: pip install crilio
      - run: crilio run
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
"""
        if wf_path.exists() and not force:
            console.print(f"[yellow]{wf_path} already exists — skipping[/]")
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
        if json_output:
            console.print_json(data={"error": f"Missing credentials: {env_hint} not set", "hint": f"export {env_hint}={key_hint} (or add to .env / GitHub Secrets)"})
        else:
            err_console.print(Panel(f"[red]Missing credentials[/] — set {env_hint}\n\n  export {env_hint}={key_hint}\n  [dim]Add it to .env or GitHub Secrets[/]", title="auth error", border_style="red"))
        raise typer.Exit(2)

    console.print("[bold]🧪 Crilio Test Runner Started[/]")
    console.print(f"[dim]Found {len(cfg.tests)} test(s)...[/]")
    console.print()

    if not json_output:
        console.print(Panel.fit(f"[bold]Crilio gate[/] • {len(cfg.tests)} tests • {sum(len(t.rules) for t in cfg.tests)} rules • [cyan]{global_provider.name}[/]/[cyan]{global_provider.model}[/] → judge [cyan]{global_provider.judge_model}[/]", border_style="dim"))

    results: list[dict] = []
    total_pass = 0
    total_fail = 0

    for idx, test in enumerate(cfg.tests, 1):
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
        }
        try:
            tgt_client = make_client(tgt_provider)
            target_res = call_target(tgt_client, provider=tgt_provider.name, model=tgt_provider.model, prompt=test.prompt, system=test.system or cfg.system)
            per_test["response"] = target_res.response
            per_test["latency_ms"] = target_res.latency_ms
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
                _render_test_simple(idx, per_test)
                _render_test(console, per_test, verbose)
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
            if jr.passed:
                total_pass += 1
            else:
                total_fail += 1
                all_pass = False
        per_test["passed"] = all_pass
        results.append(per_test)
        if not json_output:
            _render_test_simple(idx, per_test)
            _render_test(console, per_test, verbose)

    elapsed = time.perf_counter() - t_start
    gate_passed = total_fail == 0

    if json_output:
        payload = {
            "gate": "PASS" if gate_passed else "FAIL",
            "elapsed_s": round(elapsed, 2),
            "summary": {"passed": total_pass, "failed": total_fail, "total": total_pass + total_fail},
            "tests": results,
        }
        console.print_json(data=payload)
    else:
        _render_summary(gate_passed, total_pass, total_fail, elapsed)

    gha_enabled = pathlib.Path(".github/workflows/crilio.yml").exists() or os.getenv("GITHUB_ACTIONS") == "true"
    if not gha_enabled:
        if not gate_passed:
            console.print("[yellow]Note: Gate failed locally — not blocking (GitHub Actions not enabled). Enable via crilio init → Yes to GitHub Actions[/]")
        raise typer.Exit(0)
    raise typer.Exit(0 if gate_passed else 1)


def _render_test_simple(idx: int, test: dict):
    status = "✅ PASSED" if test["passed"] else "❌ FAILED"
    console.print(f"\n[bold]Test {idx}: {test['name']}[/]")
    console.print(f"   Status: {status}")
    if not test["passed"]:
        for r in test["rules"]:
            if not r["passed"]:
                console.print(f"   Reason: {r.get('reasoning','')[:200]}")
                break
    else:
        console.print(f"   Reason: All {len(test['rules'])} rules passed")
    console.print(f"   [dim]{test['provider']}/{test['model']} • {test['latency_ms']}ms[/]")


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


def _render_summary(passed: bool, ok: int, fail: int, elapsed: float):
    total = ok + fail
    if passed:
        console.print(f"\n[green bold]✓ Gate passed[/] — {ok}/{total} rules • {elapsed:.1f}s")
    else:
        console.print(f"\n[red bold]✗ Gate failed[/] — {fail}/{total} FAILED • {elapsed:.1f}s")
        if pathlib.Path(".github/workflows/crilio.yml").exists() or os.getenv("GITHUB_ACTIONS") == "true":
            console.print("[dim]blocking PR[/]")


if __name__ == "__main__":
    app()

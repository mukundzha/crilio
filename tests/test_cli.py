import pathlib
import tempfile
import textwrap

from typer.testing import CliRunner

from crilio.cli import app
from crilio.config import load_config

runner = CliRunner()

MIN_YAML = textwrap.dedent("""
provider: openai
model: gpt-4o-mini
tests:
  - name: "Hello"
    prompt: "Say hi"
    rules:
      - "Must contain hi"
""")


def test_load_config_ok():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(MIN_YAML)
        f.flush()
        cfg = load_config(f.name)
        assert len(cfg.tests) == 1
        assert cfg.provider == "openai"
        pathlib.Path(f.name).unlink()


def test_load_config_budget():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(MIN_YAML.replace("tests:", "settings:\n  budget_usd: 0.25\ntests:"))
        f.flush()
        cfg = load_config(f.name)
        assert cfg.budget_usd == 0.25
        pathlib.Path(f.name).unlink()


def test_init_creates_file():
    with runner.isolated_filesystem():
        res = runner.invoke(app, ["init"])
        assert res.exit_code == 0
        assert pathlib.Path("crilio.yaml").exists()
        res2 = runner.invoke(app, ["init"])
        assert res2.exit_code == 1
        res3 = runner.invoke(app, ["init", "--force"])
        assert res3.exit_code == 0


def test_run_dry_run():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(MIN_YAML)
        res = runner.invoke(app, ["run", "--dry-run"])
        assert res.exit_code == 0
        assert "Config valid" in res.stdout


def test_run_dry_run_json():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(MIN_YAML)
        res = runner.invoke(app, ["run", "--dry-run", "--json"])
        assert res.exit_code == 0
        assert "dry_run" in res.stdout


def test_run_missing_config():
    with runner.isolated_filesystem():
        res = runner.invoke(app, ["run", "--dry-run"])
        assert res.exit_code == 2


def test_version():
    res = runner.invoke(app, ["--version"])
    assert res.exit_code == 0

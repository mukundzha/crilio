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
        f.write(MIN_YAML.replace("tests:", "settings:\n  max_monthly_budget_usd: 0.25\ntests:"))
        f.flush()
        cfg = load_config(f.name)
        assert cfg.max_monthly_budget_usd == 0.25
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


def test_validate():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(MIN_YAML)
        res = runner.invoke(app, ["validate"])
        assert res.exit_code == 0
        assert "Configuration valid" in res.stdout
        assert "Provider: openai" in res.stdout


def test_validate_json():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(MIN_YAML)
        res = runner.invoke(app, ["validate", "--json"])
        assert res.exit_code == 0
        assert '"valid": true' in res.stdout


def test_validate_invalid_config():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text("tests:\n  - name: duplicate\n    prompt: hi\n    rules: [ok]\n  - name: duplicate\n    prompt: hello\n    rules: [ok]\n")
        res = runner.invoke(app, ["validate"])
        assert res.exit_code == 2
        assert "Configuration invalid" in res.stderr


def test_validate_missing_config():
    with runner.isolated_filesystem():
        res = runner.invoke(app, ["validate"])
        assert res.exit_code == 2


def test_version():
    res = runner.invoke(app, ["--version"])
    assert res.exit_code == 0


TAGGED_YAML = textwrap.dedent("""
provider: openai
model: gpt-4o-mini
tests:
  - name: "A"
    prompt: "hi"
    rules: ["Must contain hi"]
    tags: ["smoke"]
  - name: "B"
    prompt: "hello"
    rules: ["Must contain hello"]
    tags: ["regression"]
  - name: "C"
    prompt: "hey"
    rules: ["Must contain hey"]
""")

def test_load_config_with_tags():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(TAGGED_YAML)
        f.flush()
        cfg = load_config(f.name)
        assert cfg.tests[0].tags == ["smoke"]
        assert cfg.tests[2].tags is None
        pathlib.Path(f.name).unlink()

def test_init_contains_tags():
    with runner.isolated_filesystem():
        res = runner.invoke(app, ["init"])
        assert res.exit_code == 0
        content = pathlib.Path("crilio.yaml").read_text()
        assert "Refund Policy Check" in content

def test_run_tag_filters_dry_run():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(TAGGED_YAML)
        res = runner.invoke(app, ["run", "--dry-run", "--tag", "smoke"])
        assert res.exit_code == 0
        assert "Filtering by tag 'smoke': Running 1 of 3 tests." in res.stdout
        assert "Config valid" in res.stdout

def test_run_tag_no_match_exits_zero():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(TAGGED_YAML)
        res = runner.invoke(app, ["run", "--dry-run", "--tag", "nonexistent"])
        assert res.exit_code == 0
        assert "No tests found with tag 'nonexistent'" in res.stdout

def test_run_tag_skips_untagged():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(TAGGED_YAML)
        res = runner.invoke(app, ["run", "--dry-run", "--tag", "regression"])
        assert res.exit_code == 0
        assert "Running 1 of 3 tests" in res.stdout

def test_run_no_tag_runs_all():
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(TAGGED_YAML)
        res = runner.invoke(app, ["run", "--dry-run"])
        assert res.exit_code == 0
        assert "3 tests" in res.stdout


def test_pr_comment_noop_locally(monkeypatch):
    from unittest.mock import patch
    from crilio.cli import _post_github_pr_comment
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with patch("crilio.cli.requests.post") as mock:
        _post_github_pr_comment("T", "R", "resp", "reason")
        mock.assert_not_called()

def test_pr_comment_posts_in_actions(monkeypatch):
    from unittest.mock import patch, MagicMock
    from crilio.cli import _post_github_pr_comment
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/12/merge")
    with patch("crilio.cli.requests.post") as mock:
        mock.return_value = MagicMock(status_code=201)
        _post_github_pr_comment("MyTest", "Must mention 30 days", "Hello world", "Judge reason")
        assert mock.call_count == 1
        url = mock.call_args.args[0]
        assert "/repos/owner/repo/issues/12/comments" in url
        headers = mock.call_args.kwargs["headers"]
        assert headers["Authorization"] == "token fake-token"
        assert "fake-token" not in mock.call_args.kwargs["json"]["body"]
        assert "MyTest" in mock.call_args.kwargs["json"]["body"]

def test_pr_comment_resilience_on_timeout(monkeypatch):
    from unittest.mock import patch
    from crilio.cli import _post_github_pr_comment
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/12/merge")
    with patch("crilio.cli.requests.post", side_effect=Exception("timeout")):
        _post_github_pr_comment("T", "R", "resp", "reason")

def test_pr_comment_bad_ref_silent(monkeypatch):
    from unittest.mock import patch
    from crilio.cli import _post_github_pr_comment
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF", "badref")
    with patch("crilio.cli.requests.post") as mock:
        _post_github_pr_comment("T", "R", "resp", "reason")
        mock.assert_not_called()

def test_pr_comment_missing_env_noop(monkeypatch):
    from unittest.mock import patch
    from crilio.cli import _post_github_pr_comment
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/12/merge")
    with patch("crilio.cli.requests.post") as mock:
        _post_github_pr_comment("T", "R", "resp", "reason")
        mock.assert_not_called()

def test_run_failure_posts_pr_comment(monkeypatch):
    from unittest.mock import patch, MagicMock
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/42/merge")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    yaml = textwrap.dedent("""
provider: openai
model: gpt-4o-mini
tests:
  - name: "FailTest"
    prompt: "hi"
    rules: ["Must contain hi"]
""")
    with runner.isolated_filesystem():
        pathlib.Path("crilio.yaml").write_text(yaml)
        mock_target = MagicMock()
        mock_target.response = "bad response"
        mock_target.latency_ms = 10
        mock_target.usage.input_tokens = 1
        mock_target.usage.output_tokens = 1
        mock_target.cost_usd = 0.001
        mock_judge = MagicMock()
        mock_judge.rule = "Must contain hi"
        mock_judge.passed = False
        mock_judge.reasoning = "Missing hi"
        mock_judge.usage.input_tokens = 1
        mock_judge.usage.output_tokens = 1
        mock_judge.cost_usd = 0.001
        with patch("crilio.cli.make_client", return_value=MagicMock()):
            with patch("crilio.cli.call_target", return_value=mock_target):
                with patch("crilio.cli.judge_rule", return_value=mock_judge):
                    with patch("crilio.cli.requests.post") as mock_post:
                        mock_post.return_value = MagicMock(status_code=201)
                        res = runner.invoke(app, ["run"])
                        assert mock_post.call_count == 1
                        assert "42" in mock_post.call_args.args[0]

def test_pr_comment_never_logs_token(monkeypatch, capsys):
    from unittest.mock import patch
    from crilio.cli import _post_github_pr_comment
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "super-secret-token-xyz")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/12/merge")
    with patch("crilio.cli.requests.post", side_effect=Exception("401 Unauthorized")):
        _post_github_pr_comment("T", "R", "resp", "reason")
    captured = capsys.readouterr()
    assert "super-secret-token-xyz" not in captured.out
    assert "super-secret-token-xyz" not in captured.err

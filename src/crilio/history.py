from __future__ import annotations

import datetime
import json
import pathlib
import subprocess
from typing import Any


def _git_sha() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _git_branch() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _history_dir() -> pathlib.Path:
    return pathlib.Path(".crilio") / "runs"


def _history_file() -> pathlib.Path:
    return pathlib.Path(".crilio") / "history.jsonl"


def save_run(payload: dict[str, Any]) -> pathlib.Path | None:
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        sha = _git_sha()
        branch = _git_branch()
        record = {
            "timestamp": now.isoformat(),
            "git_sha": sha,
            "git_branch": branch,
            **payload,
        }
        d = _history_dir()
        d.mkdir(parents=True, exist_ok=True)
        fname = now.strftime("%Y%m%d_%H%M%S")
        if sha:
            fname += f"_{sha}"
        path = d / f"{fname}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        hf = _history_file()
        hf.parent.mkdir(parents=True, exist_ok=True)
        with hf.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return path
    except Exception:
        return None


def load_history(limit: int = 20) -> list[dict[str, Any]]:
    hf = _history_file()
    if not hf.exists():
        return []
    try:
        lines = hf.read_text(encoding="utf-8").strip().splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        return records[-limit:][::-1]
    except Exception:
        return []


def load_last_payload() -> dict[str, Any] | None:
    hf = _history_file()
    if not hf.exists():
        return None
    try:
        lines = [line for line in hf.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception:
        return None

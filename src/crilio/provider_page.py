from __future__ import annotations

import os
import pathlib
import sys

from crilio.provider import PROVIDER_DEFAULTS
from crilio.setup import load_dotenv_if_exists, mask_key, persist_env, validate_key

def _status_for() -> tuple[str, str]:
    key = os.getenv("OPENAI_API_KEY") or ""
    if key:
        return ("configured", mask_key(key))
    return ("missing", "-")

def show_provider_page(
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    yes: bool = False,
    skip_validate: bool = False,
    json_output: bool = False,
    action: str | None = None,
) -> int:
    load_dotenv_if_exists()
    if json_output:
        import json
        data = {
            "openai": {
                "env_key": "OPENAI_API_KEY",
                "configured": bool(os.getenv("OPENAI_API_KEY")),
                "key_masked": mask_key(os.getenv("OPENAI_API_KEY", "")),
                "model": PROVIDER_DEFAULTS["openai"]["model"],
                "base_url": PROVIDER_DEFAULTS["openai"]["base_url"],
            }
        }
        print(json.dumps(data, indent=2))
        return 0
    if provider and provider.lower() != "openai":
        print("Only openai is supported", file=sys.stderr)
        return 2
    if api_key and yes:
        if not skip_validate:
            ok, msg = validate_key("openai", api_key)
            if not ok and "network error" not in msg:
                print(f"Validation failed: {msg}", file=sys.stderr)
                return 2
        target = persist_env("openai", api_key)
        print(f"Saved OPENAI_API_KEY to {target} ({mask_key(api_key)})")
        return 0
    if action == "list":
        status, masked = _status_for()
        print(f"Provider: openai")
        print(f"Env Key: OPENAI_API_KEY")
        print(f"Status: {status}")
        print(f"Key: {masked}")
        print(f"Model: {PROVIDER_DEFAULTS['openai']['model']}")
        print(f"Base URL: {PROVIDER_DEFAULTS['openai']['base_url']}")
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Usage:", file=sys.stderr)
        print("  crilio provider --provider openai --api-key sk-... --yes", file=sys.stderr)
        print("  crilio provider --list", file=sys.stderr)
        print("  crilio provider --list --json", file=sys.stderr)
        return 2
    print("Provider management - openai only")
    print("Commands:")
    print("  crilio provider --list")
    print("  crilio provider --list --json")
    print("  crilio provider --provider openai --api-key sk-... --yes")
    status, masked = _status_for()
    print(f"Current: openai - {status} - {masked}")
    return 0

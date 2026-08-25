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
            name: {
                "env_key": defaults["env_key"],
                "configured": bool(os.getenv(defaults["env_key"])),
                "key_masked": mask_key(os.getenv(defaults["env_key"], "")),
                "model": defaults["model"],
                "base_url": defaults.get("base_url"),
            }
            for name, defaults in PROVIDER_DEFAULTS.items()
        }
        print(json.dumps(data, indent=2))
        return 0
    if provider and provider.lower() not in PROVIDER_DEFAULTS:
        print("Supported providers are openai and anthropic", file=sys.stderr)
        return 2
    if api_key and yes:
        provider_name = (provider or "openai").lower()
        if not skip_validate:
            ok, msg = validate_key(provider_name, api_key)
            if not ok and "network error" not in msg:
                print(f"Validation failed: {msg}", file=sys.stderr)
                return 2
        target = persist_env(provider_name, api_key)
        env_key = PROVIDER_DEFAULTS[provider_name]["env_key"]
        print(f"Saved {env_key} to {target} ({mask_key(api_key)})")
        return 0
    if action == "list":
        for name, defaults in PROVIDER_DEFAULTS.items():
            key = os.getenv(defaults["env_key"], "")
            status = "configured" if key else "missing"
            print(f"Provider: {name}")
            print(f"Env Key: {defaults['env_key']}")
            print(f"Status: {status}")
            print(f"Key: {mask_key(key)}")
            print(f"Model: {defaults['model']}")
            if defaults.get("base_url"):
                print(f"Base URL: {defaults['base_url']}")
            print()
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Usage:", file=sys.stderr)
        print("  crilio provider --provider openai|anthropic --api-key ... --yes", file=sys.stderr)
        print("  crilio provider --list", file=sys.stderr)
        print("  crilio provider --list --json", file=sys.stderr)
        return 2
    print("Provider management - openai or anthropic")
    print("Commands:")
    print("  crilio provider --list")
    print("  crilio provider --list --json")
    print("  crilio provider --provider openai|anthropic --api-key ... --yes")
    for name, defaults in PROVIDER_DEFAULTS.items():
        key = os.getenv(defaults["env_key"], "")
        status = "configured" if key else "missing"
        print(f"Current: {name} - {status} - {mask_key(key)}")
    return 0

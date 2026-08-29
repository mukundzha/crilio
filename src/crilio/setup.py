from __future__ import annotations

import os
import pathlib
import sys


def mask_key(key: str) -> str:
    if not key:
        return "-"
    if len(key) <= 8:
        return key[:2] + "***"
    return key[:4] + "***" + key[-4:]


def load_dotenv_if_exists() -> None:
    path = pathlib.Path(".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def persist_env(provider: str, api_key: str) -> pathlib.Path:
    env_keys = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    if provider not in env_keys:
        raise ValueError("supported providers: openai, anthropic")
    env_key = env_keys[provider]
    target = pathlib.Path(".env")
    lines = target.read_text().splitlines() if target.exists() else []
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith(f"{env_key}="):
            output.append(f"{env_key}={api_key}")
            replaced = True
        else:
            output.append(line)
    if not replaced:
        if output and output[-1].strip():
            output.append("")
        output.append(f"{env_key}={api_key}")
    target.write_text("\n".join(output) + "\n")
    gitignore = pathlib.Path(".gitignore")
    if gitignore.exists():
        content = gitignore.read_text()
        if ".env" not in content:
            gitignore.write_text(content.rstrip() + "\n.env\n")
    else:
        gitignore.write_text(".env\n")
    return target


def validate_key(provider: str, api_key: str) -> tuple[bool, str]:
    if provider not in {"openai", "anthropic"}:
        return False, "supported providers: openai, anthropic"
    if not api_key or len(api_key.strip()) < 8:
        return False, "key too short"
    if provider == "openai" and not api_key.startswith("sk-"):
        return False, "OpenAI keys start with sk- (platform.openai.com/api-keys)"
    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            Anthropic(api_key=api_key).models.list()
            return True, "ok"
        from openai import OpenAI

        OpenAI(api_key=api_key, timeout=6).models.list()
        return True, "ok"
    except Exception as error:
        message = str(error)
        if "401" in message or "invalid_api_key" in message.lower():
            return False, f"401 Invalid API key - {message[:100]}"
        if "timeout" in message.lower() or "connection" in message.lower():
            return False, f"network error - {message[:80]} (saved, will retry on run)"
        return False, message[:150]


def interactive_setup(
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    yes: bool = False,
    skip_validate: bool = False,
    force: bool = False,
) -> int:
    del base_url, force
    load_dotenv_if_exists()
    provider_name = (provider or "openai").lower()
    if provider_name not in {"openai", "anthropic"}:
        print("Error: supported providers are openai and anthropic", file=sys.stderr)
        return 2
    if not api_key:
        print(
            "Usage: crilio setup --provider openai|anthropic --api-key ... --yes",
            file=sys.stderr,
        )
        return 2
    if not skip_validate:
        ok, message = validate_key(provider_name, api_key)
        if not ok and "network error" not in message:
            print(f"Validation failed: {message}", file=sys.stderr)
            return 2
    target = persist_env(provider_name, api_key)
    env_key = "OPENAI_API_KEY" if provider_name == "openai" else "ANTHROPIC_API_KEY"
    print(f"Saved {env_key} to {target} ({mask_key(api_key)})")
    print("Next: crilio run --dry-run -> crilio run")
    return 0

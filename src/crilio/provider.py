from __future__ import annotations

import json
import os
import pathlib
import time
from dataclasses import dataclass
from typing import Any

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "model": "gpt-4o-mini",
        "judge_model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
    },
    "anthropic": {
        "model": "claude-3-5-sonnet-latest",
        "judge_model": "claude-3-5-haiku-latest",
        "env_key": "ANTHROPIC_API_KEY",
    },
}

VALID_PROVIDERS = set(PROVIDER_DEFAULTS)


def _is_valid_key_for_provider(provider: str, key: str, base_url: str | None = None) -> bool:
    if not key:
        return False
    k = key.strip()
    if provider == "openai":
        return k.startswith("sk-") and not k.startswith("sk-ant-")
    if provider == "anthropic":
        return k.startswith("sk-ant-")
    return True


MODEL_CATALOG: dict[str, list[str]] = {
    "openai": [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "o1-mini",
    ],
    "anthropic": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"],
}


@dataclass(frozen=True)
class ResolvedProvider:
    name: str
    model: str
    judge_model: str
    base_url: str | None
    api_key: str | None


def resolve_provider(
    *,
    provider: str | None = None,
    model: str | None = None,
    judge_model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    fallback_provider: str = "openai",
) -> ResolvedProvider:
    name = (provider or fallback_provider or "openai").lower().strip()
    if name not in VALID_PROVIDERS:
        raise ValueError(
            f"unknown provider '{name}' — choose one of: {', '.join(sorted(VALID_PROVIDERS))}"
        )
    defaults = PROVIDER_DEFAULTS[name]
    resolved_model = model or defaults["model"]
    resolved_judge = judge_model or defaults["judge_model"]
    resolved_base = base_url or defaults.get("base_url")
    env_key = defaults["env_key"]
    resolved_key = api_key or os.getenv(env_key)
    if resolved_key and not _is_valid_key_for_provider(name, resolved_key, resolved_base):
        hint = "sk-ant-..." if name == "anthropic" else "sk-..."
        raise ValueError(
            f"Invalid API key for provider '{name}' — expected {hint} for {env_key}, got '{resolved_key[:8]}...'. Check {env_key}."
        )
    return ResolvedProvider(
        name=name,
        model=resolved_model,
        judge_model=resolved_judge,
        base_url=resolved_base,
        api_key=resolved_key,
    )


def resolve_for_test(
    *,
    global_provider: ResolvedProvider,
    test_provider: str | None,
    test_model: str | None,
    test_judge_model: str | None,
    cli_base_url: str | None,
    cli_api_key: str | None,
) -> tuple[ResolvedProvider, ResolvedProvider]:
    if test_provider or test_model:
        tgt = resolve_provider(
            provider=test_provider or global_provider.name,
            model=test_model or global_provider.model,
            judge_model=None,
            base_url=cli_base_url or global_provider.base_url,
            api_key=cli_api_key or global_provider.api_key,
            fallback_provider=global_provider.name,
        )
    else:
        tgt = global_provider
    judge = resolve_provider(
        provider=global_provider.name,
        model=None,
        judge_model=test_judge_model or global_provider.judge_model,
        base_url=cli_base_url or global_provider.base_url,
        api_key=cli_api_key or global_provider.api_key,
        fallback_provider=global_provider.name,
    )
    if test_judge_model:
        judge = ResolvedProvider(
            name=judge.name,
            model=judge.model,
            judge_model=test_judge_model,
            base_url=judge.base_url,
            api_key=judge.api_key,
        )
    return tgt, judge


def infer_provider_from_env() -> str | None:
    if os.getenv("OPENAI_API_KEY") or os.getenv("CRILIO_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return None


def validate_api_key(
    provider: str, api_key: str, base_url: str | None = None
) -> tuple[bool, str]:
    if not api_key or len(api_key.strip()) < 6:
        return False, "key too short"
    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            Anthropic(api_key=api_key).models.list()
            return True, "ok"
        from openai import OpenAI

        kwargs: dict[str, str] = {"api_key": api_key}
        bp = base_url or PROVIDER_DEFAULTS.get(provider, {}).get("base_url")
        if bp:
            kwargs["base_url"] = bp
        client = OpenAI(**kwargs, timeout=6)
        client.models.list()
        return True, "ok"
    except Exception as e:
        return False, str(e)[:200]


def _cache_path() -> pathlib.Path:
    p = pathlib.Path.home() / ".config" / "crilio" / "models.json"
    return p


def _is_chat_model(mid: str) -> bool:
    mid = mid.lower()
    if any(
        x in mid
        for x in [
            "embedding",
            "whisper",
            "tts",
            "dall",
            "moderation",
            "babbage",
            "davinci",
        ]
    ):
        return False
    return True


def list_models(
    provider: str,
    api_key: str | None = None,
    base_url: str | None = None,
    use_cache: bool = True,
    max_age_h: int = 24,
) -> tuple[list[str], bool]:
    curated = MODEL_CATALOG.get(provider, MODEL_CATALOG["openai"])
    key = (
        api_key
        or os.getenv(PROVIDER_DEFAULTS.get(provider, {}).get("env_key", ""))
        or os.getenv("CRILIO_API_KEY")
    )
    if not key:
        return curated, False
    cache = _cache_path()
    if use_cache and cache.exists():
        try:
            age = time.time() - cache.stat().st_mtime
            if age < max_age_h * 3600:
                data = json.loads(cache.read_text())
                cached = data.get(provider)
                if cached and isinstance(cached, list) and len(cached) > 0:
                    return cached, True
        except Exception:
            pass
    try:
        if provider == "anthropic":
            from anthropic import Anthropic

            resp = Anthropic(api_key=key).models.list()
            ids = sorted(m.id for m in resp.data)
            if ids:
                return ids, True
            return curated, False
        kwargs: dict[str, str] = {"api_key": key}
        bp = base_url or PROVIDER_DEFAULTS.get(provider, {}).get("base_url")
        if bp:
            kwargs["base_url"] = bp
        from openai import OpenAI  # noqa: F401

        client = OpenAI(**kwargs, timeout=8)
        resp = client.models.list()
        ids = [m.id for m in resp.data if _is_chat_model(m.id)]
        ids = sorted(ids)
        if not ids:
            return curated, False
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            existing: dict = {}
            if cache.exists():
                try:
                    existing = json.loads(cache.read_text())
                except Exception:
                    existing = {}
            existing[provider] = ids
            cache.write_text(json.dumps(existing, indent=2))
        except Exception:
            pass
        return ids, True
    except Exception:
        return curated, False


def load_dotenv():
    for p in [os.path.join(os.getcwd(), ".env")]:
        if os.path.exists(p):
            try:
                with open(p) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and v and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


def make_client(provider: ResolvedProvider) -> Any:
    load_dotenv()
    api_key = (
        provider.api_key
        or os.getenv(PROVIDER_DEFAULTS.get(provider.name, {}).get("env_key", ""))
        or os.getenv("CRILIO_API_KEY")
    )
    if not api_key:
        env = PROVIDER_DEFAULTS.get(provider.name, {}).get("env_key", "OPENAI_API_KEY")
        raise RuntimeError(
            f"Missing credentials for provider '{provider.name}' — set {env} or add it to .env"
        )
    if not _is_valid_key_for_provider(provider.name, api_key, provider.base_url):
        env = PROVIDER_DEFAULTS.get(provider.name, {}).get("env_key", "OPENAI_API_KEY")
        hint = "sk-ant-..." if provider.name == "anthropic" else "sk-..."
        raise RuntimeError(
            f"Invalid API key for provider '{provider.name}' — expected {hint} for {env}, got '{api_key[:8]}...'. Use the correct provider or set {env}."
        )
    if provider.name == "anthropic":
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic support requires the 'anthropic' package; install crilio[anthropic]"
            ) from exc
        return Anthropic(api_key=api_key)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI-compatible providers require the 'openai' package"
        ) from exc
    kwargs: dict[str, str] = {"api_key": api_key}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    return OpenAI(**kwargs)

from __future__ import annotations

import os
import pathlib
import re
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

_LEAK_RE = re.compile(r"sk-(proj|ant)-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9_-]{20,}")

ProviderName = Literal["openai", "anthropic"]


class Settings(BaseModel):
    target_model: str = "gpt-4o"
    judge_model: str = "gpt-4o-mini"
    max_monthly_budget_usd: Optional[float] = Field(None, ge=0)

    @field_validator("max_monthly_budget_usd", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        if v == "" or v == "null":
            return None
        return v


class TargetCommand(BaseModel):
    command: str = Field(..., min_length=1)

    @field_validator("command")
    @classmethod
    def _validate_command(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("target.command must not be empty")
        return v.strip()


class TestCase(BaseModel):
    name: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    system: Optional[str] = None
    rules: list[str] = Field(..., min_length=1)
    provider: Optional[ProviderName] = None
    model: Optional[str] = None
    judge_model: Optional[str] = None
    tags: Optional[list[str]] = None
    target: Optional[TargetCommand] = None
    skip: bool = False

    @field_validator("target", mode="before")
    @classmethod
    def _coerce_target(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("target command must not be empty")
            return {"command": v}
        return v

    @field_validator("rules")
    @classmethod
    def validate_rules(cls, v: list[str]) -> list[str]:
        for r in v:
            if not r.strip():
                raise ValueError("rule must not be empty")
        return v


class CrilioConfig(BaseModel):
    provider: Optional[ProviderName] = None
    model: Optional[str] = None
    judge_model: Optional[str] = None
    base_url: Optional[str] = None
    system: Optional[str] = None
    settings: Optional[Settings] = None
    max_monthly_budget_usd: Optional[float] = Field(None, ge=0)
    tests: list[TestCase] = Field(..., min_length=1)

    @field_validator("max_monthly_budget_usd", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        if v == "" or v == "null":
            return None
        return v

    @field_validator("tests")
    @classmethod
    def validate_tests(cls, v: list[TestCase]) -> list[TestCase]:
        names = [t.name for t in v]
        if len(names) != len(set(names)):
            raise ValueError("test names must be unique")
        return v

    @model_validator(mode="after")
    def _normalize_settings(self):
        if self.settings:
            if not self.model:
                self.model = self.settings.target_model
            if not self.judge_model:
                self.judge_model = self.settings.judge_model
            if self.max_monthly_budget_usd is None:
                self.max_monthly_budget_usd = self.settings.max_monthly_budget_usd
            if not self.provider:
                self.provider = "openai"
        if not self.model and self.provider == "openai":
            self.model = "gpt-4o-mini"
        if not self.judge_model:
            self.judge_model = self.model or "gpt-4o-mini"
        return self


_ENV_VAR_RE = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _expand_env_vars(text: str) -> str:
    def repl(m):
        if m.group(3):
            return os.getenv(m.group(3), "")
        key, default = m.group(1), m.group(2)
        val = os.getenv(key)
        if val is None:
            return default if default is not None else m.group(0)
        return val
    return _ENV_VAR_RE.sub(repl, text)


def load_config(path: str | pathlib.Path) -> CrilioConfig:
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {p}")
    text = p.read_text(encoding="utf-8")
    text = _expand_env_vars(text)
    if _LEAK_RE.search(text):
        raise ValueError(
            "Potential API key detected in crilio.yaml — remove keys, use .env / GitHub Secrets (OPENAI_API_KEY / ANTHROPIC_API_KEY) instead"
        )
    if re.search(r"(?i)\bapi[_-]?key\s*:", text):
        raise ValueError(
            "Potential api_key field detected in crilio.yaml — use env var instead"
        )
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("crilio.yaml must be a mapping")
    if "tests" not in raw:
        raise ValueError("crilio.yaml missing required key: 'tests'")
    if "max_monthly_budget_usd" in raw and "budget_usd" in raw:
        raise ValueError("use max_monthly_budget_usd (budget_usd is deprecated)")
    if "budget_usd" in raw:
        raw["max_monthly_budget_usd"] = raw.pop("budget_usd")
    if "settings" in raw and isinstance(raw["settings"], dict):
        s = raw["settings"]
        if "budget_usd" in s and "max_monthly_budget_usd" not in s:
            s["max_monthly_budget_usd"] = s.pop("budget_usd")
        if "target_model" in s and "model" not in raw:
            raw["model"] = s["target_model"]
        if "judge_model" in s and "judge_model" not in raw:
            raw["judge_model"] = s["judge_model"]
        if "max_monthly_budget_usd" in s and "max_monthly_budget_usd" not in raw:
            raw["max_monthly_budget_usd"] = s["max_monthly_budget_usd"]
        if "provider" not in raw:
            raw["provider"] = "openai"
    return CrilioConfig.model_validate(raw)


def dump_yaml(cfg: CrilioConfig) -> str:
    data: dict = {}
    target_model = cfg.model or (
        cfg.settings.target_model if cfg.settings else "gpt-4o"
    )
    judge_model = cfg.judge_model or (
        cfg.settings.judge_model if cfg.settings else "gpt-4o-mini"
    )
    data["settings"] = {
        "target_model": target_model,
        "judge_model": judge_model,
        "max_monthly_budget_usd": cfg.max_monthly_budget_usd,
    }
    if cfg.system:
        data["system"] = cfg.system
    data["tests"] = [t.model_dump(exclude_none=True) for t in cfg.tests]
    header = "# crilio.yaml\n# Generated by `crilio init` — edit to match your app\n\n"
    raw = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    raw = raw.replace("max_monthly_budget_usd: null", "max_monthly_budget_usd:")
    return header + raw


DEFAULT_CONFIG_YAML = """\
# crilio.yaml — CI/CD quality gate for AI
# Keys in .env (OPENAI_API_KEY / ANTHROPIC_API_KEY) — never commit keys here
# Env interpolation: ${VAR} / ${VAR:-default}

settings:
  provider: ${CRILIO_PROVIDER:-openai}
  target_model: ${CRILIO_MODEL:-gpt-4o-mini}
  judge_model: ${CRILIO_JUDGE_MODEL:-gpt-4o-mini}
  max_monthly_budget_usd: ${CRILIO_BUDGET:-10.0}
  # system: "You are a concise, professional support assistant."

tests:
  - name: "Refund Policy Check"
    prompt: "How long do I have to return a product?"
    rules:
      - "Must mention the 30-day return window."
      - "Must NOT mention competitor names like Amazon or Walmart."
    tags: ["refund", "policy"]

  - name: "JSON Format Check"
    prompt: "Return my user status as JSON."
    rules:
      - "Must return valid JSON with keys 'status' and 'user_id'."
      - "Must NOT include apologies or extra prose."
    tags: ["json", "formatting"]

  # --- Kitchen-sink example (every feature) — uncomment to use ---
  # - name: "Full Feature Showcase"
  #   prompt: "Summarize our refund policy for a premium customer in JSON."
  #   system: "You are a helpful support assistant. Be concise and professional."
  #   provider: openai
  #   model: gpt-4o-mini
  #   judge_model: gpt-4o-mini
  #   tags: ["premium", "refund", "json", "smoke"]
  #   skip: false
  #   target:
  #     command: "python bot.py '{{prompt}}'"
  #   rules:
  #     - "Must mention the 30-day return window."
  #     - "Must return valid JSON with keys 'summary' and 'days'."
  #     - "Must NOT mention competitor names like Amazon or Walmart."
  #     - "Must be concise (under 100 words)."
"""

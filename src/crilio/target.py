from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass

from crilio.cost import Usage, cost_usd


@dataclass
class TargetResult:
    response: str
    latency_ms: int
    model: str
    usage: Usage
    cost_usd: float


SYSTEM_PROMPT = (
    "<role>You are a deterministic, production-grade AI execution engine.</role>\n"
    "<objective>Fulfill the user's prompt with absolute precision. Adhere strictly to all provided constraints.</objective>\n"
    "<constraints>\n"
    "1. NO CONVERSATIONAL FILLER: Do not use greetings, apologies, or introductory text (e.g., 'Here is your response:'). Output ONLY the requested content.\n"
    "2. STRICT FORMATTING: If JSON, code, or a specific schema is requested, output ONLY valid, parseable syntax. Never wrap output in markdown blocks unless explicitly instructed.\n"
    "3. ZERO HALLUCINATIONS: Do not invent facts, policies, or external data not present in the prompt context.\n"
    "4. ABSOLUTE COMPLIANCE: Follow every negative and positive constraint in the user prompt literally. Do not summarize or interpret constraints loosely.\n"
    "</constraints>"
)


def call_target(
    client: object,
    *,
    provider: str = "openai",
    model: str,
    prompt: str,
    system: str | None = None,
    max_retries: int = 2,
) -> TargetResult:
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            t0 = time.perf_counter()
            if provider == "anthropic":
                resp = client.messages.create(
                    model=model,
                    system=system or SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=4096,
                )
                content = "".join(
                    block.text
                    for block in resp.content
                    if getattr(block, "type", None) == "text"
                )
                usage = Usage(resp.usage.input_tokens, resp.usage.output_tokens)
            else:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system or SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                )
                content = resp.choices[0].message.content or ""
                raw_usage = resp.usage
                usage = Usage(
                    getattr(raw_usage, "prompt_tokens", 0),
                    getattr(raw_usage, "completion_tokens", 0),
                )
            latency = int((time.perf_counter() - t0) * 1000)
            return TargetResult(
                response=content.strip(),
                latency_ms=latency,
                model=model,
                usage=usage,
                cost_usd=cost_usd(model, usage),
            )
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"target call failed: {last_err}") from last_err


def call_target_command(
    template: str,
    prompt: str,
    timeout: int = 30,
) -> TargetResult:
    if not template or not template.strip():
        raise ValueError("target.command must not be empty")
    t0 = time.perf_counter()
    try:
        if "{{prompt}}" in template:
            cmd = template.replace("'{{prompt}}'", shlex.quote(prompt))
            cmd = cmd.replace('"{{prompt}}"', shlex.quote(prompt))
            cmd = cmd.replace("{{prompt}}", shlex.quote(prompt))
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        else:
            parts = shlex.split(template)
            if not parts:
                raise ValueError("target.command is empty")
            if shutil.which(parts[0]) is None:
                raise FileNotFoundError(f"command not found: {parts[0]}")
            proc = subprocess.run(
                parts,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        latency = int((time.perf_counter() - t0) * 1000)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:500]
            raise RuntimeError(f"command failed (exit {proc.returncode}): {err}")
        out = (proc.stdout or "").strip()
        if not out:
            out = "[empty]"
        return TargetResult(
            response=out,
            latency_ms=latency,
            model="command",
            usage=Usage(0, 0),
            cost_usd=0.0,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"command timed out after {timeout}s: {e}") from e
    except FileNotFoundError:
        raise
    except Exception as e:
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(f"command execution failed: {e}") from e

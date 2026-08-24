from __future__ import annotations

import time
from dataclasses import dataclass

from openai import OpenAI


@dataclass
class TargetResult:
    response: str
    latency_ms: int
    model: str

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
    client: OpenAI,
    *,
    model: str,
    prompt: str,
    system: str | None = None,
    max_retries: int = 2,
) -> TargetResult:
    last_err: Exception | None = None
    start = time.perf_counter()
    for attempt in range(max_retries + 1):
        try:
            t0 = time.perf_counter()
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system or SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )
            latency = int((time.perf_counter() - t0) * 1000)
            content = resp.choices[0].message.content or ""
            return TargetResult(response=content.strip(), latency_ms=latency, model=model)
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"target call failed: {last_err}") from last_err

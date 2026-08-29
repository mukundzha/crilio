from __future__ import annotations

import time
from dataclasses import dataclass

import instructor
from pydantic import BaseModel, Field

from crilio.cost import Usage, cost_usd, estimate_tokens


class JudgeVerdict(BaseModel):
    rule_passed: bool = Field(
        description="True if response satisfies the rule, False otherwise"
    )
    reasoning: str = Field(default="", description="Brief 1-sentence justification")


@dataclass
class JudgeResult:
    rule: str
    passed: bool
    reasoning: str
    latency_ms: int
    usage: Usage
    cost_usd: float


JUDGE_SYSTEM = (
    "You are a strict AI QA evaluator. Judge the RESPONSE against the RULE literally and objectively, "
    "using only the given text — no outside knowledge, no benefit of the doubt. "
    "'Must mention X' fails if X is absent; 'must not mention Y' fails if Y appears; tone/format rules fail on any deviation. "
    "Output ONLY valid JSON (no markdown, no extra text) matching: "
    '{"rule_evaluation": "PASS"|"FAIL", "reasoning": "<1-2 sentence explanation>", "evidence": "<exact quote if FAIL, else \'\'>"}. '
    "Example — RULE: Must not mention Amazon. RESPONSE: Buy it here, Amazon is cheaper. "
    'Output: {"rule_evaluation": "FAIL", "reasoning": "Response mentions the prohibited competitor Amazon.", "evidence": "Amazon is cheaper"}'
)


def judge_rule(
    client: object,
    *,
    provider: str = "openai",
    judge_model: str,
    response: str,
    rule: str,
) -> JudgeResult:
    import logging

    logging.getLogger("instructor").setLevel(logging.ERROR)
    logging.getLogger("openai").setLevel(logging.ERROR)
    patched = (
        instructor.from_anthropic(client)
        if provider == "anthropic"
        else instructor.from_openai(client, mode=instructor.Mode.TOOLS_STRICT)
    )
    t0 = time.perf_counter()
    try:
        import contextlib
        import io
        import logging

        logging.getLogger("instructor").setLevel(logging.ERROR)
        with contextlib.redirect_stderr(io.StringIO()):
            messages = [
                {"role": "system", "content": JUDGE_SYSTEM},
                {
                    "role": "user",
                    "content": f"RULE: {rule}\n\nRESPONSE:\n{response}\n\nDoes the response satisfy the rule?",
                },
            ]
            if provider == "anthropic":
                verdict = patched.messages.create(
                    model=judge_model,
                    response_model=JudgeVerdict,
                    messages=[messages[1]],
                    system=JUDGE_SYSTEM,
                    temperature=0,
                    max_tokens=1024,
                    max_retries=0,
                )
            else:
                verdict = patched.chat.completions.create(
                    model=judge_model,
                    response_model=JudgeVerdict,
                    messages=messages,
                    temperature=0,
                    max_retries=0,
                )
        latency = int((time.perf_counter() - t0) * 1000)
        judge_input = JUDGE_SYSTEM + rule + response
        usage = Usage(
            estimate_tokens(judge_input),
            estimate_tokens(verdict.reasoning),
            estimated=True,
        )
        return JudgeResult(
            rule=rule,
            passed=bool(verdict.rule_passed),
            reasoning=verdict.reasoning,
            latency_ms=latency,
            usage=usage,
            cost_usd=cost_usd(judge_model, usage),
        )
    except Exception as e:
        latency = int((time.perf_counter() - t0) * 1000)
        msg = str(e)
        if "failed_generation" in msg:
            try:
                import json as _json
                import re as _re

                fg = None
                m = _re.search(r"'failed_generation':\s*'(\{.*?\})'", msg, _re.DOTALL)
                if not m:
                    m = _re.search(
                        r'"failed_generation":\s*"(\{.*?\})"', msg, _re.DOTALL
                    )
                if m:
                    fg = m.group(1)
                else:
                    m2 = _re.search(r"failed_generation.*?(\{.*\})", msg, _re.DOTALL)
                    if m2:
                        fg = m2.group(1)
                if fg:
                    fg = fg.replace('\\"', '"').replace("\\'", "'")
                    try:
                        data = _json.loads(fg)
                    except Exception:
                        data = _json.loads(fg.replace("'", '"'))
                    if isinstance(data, dict) and "rule_evaluation" in data:
                        passed = str(data.get("rule_evaluation", "")).upper() == "PASS"
                        reasoning = (
                            data.get("reasoning", "")
                            or data.get("evidence", "")
                            or msg[:200]
                        )
                        return JudgeResult(
                            rule=rule,
                            passed=passed,
                            reasoning=reasoning[:200],
                            latency_ms=latency,
                            usage=Usage(),
                            cost_usd=0.0,
                        )
            except Exception:
                pass
        return JudgeResult(
            rule=rule,
            passed=False,
            reasoning=f"judge error: {e}",
            latency_ms=latency,
            usage=Usage(),
            cost_usd=0.0,
        )

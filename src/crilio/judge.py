from __future__ import annotations

import time
from dataclasses import dataclass

import instructor
from pydantic import BaseModel, Field

from crilio.cost import Usage, cost_usd, estimate_tokens

class JudgeVerdict(BaseModel):
    rule_passed: bool = Field(description="True if response satisfies the rule, False otherwise")
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
    "You are an elite, uncompromising AI Quality Assurance Engineer with over a decade of experience evaluating LLMs at Google/Meta scale. "
    "Your absolute priority is preventing broken, hallucinated, or non-compliant AI responses from reaching production. "
    "You are evaluating a RESPONSE against a RULE. You must act with ruthless objectivity. Do not give the benefit of the doubt. "
    "Be literal: 'Must mention X' fails if X is absent. 'Must NOT mention Y' fails if Y appears. 'Tone must be Z' fails if tone differs. "
    "Evaluate ONLY based on the provided rule and response. Do not use outside knowledge. Do not be lenient. "
    "Output strictly valid JSON only. Do not include markdown blocks (e.g., no ```json) or conversational filler. "
    "The JSON must exactly match this schema: "
    "{\"rule_evaluation\": \"<must be exactly 'PASS' or 'FAIL'>\", \"reasoning\": \"<1-2 sentence technical explanation>\", \"evidence\": \"<exact quote proving failure, or empty string if passed>\"}. "
    "Example - RULE: Must NOT mention Amazon. RESPONSE: Buy it here, Amazon is cheaper. "
    "Output: {\"rule_evaluation\": \"FAIL\", \"reasoning\": \"The response explicitly mentions the competitor Amazon, violating the negative constraint.\", \"evidence\": \"Amazon is cheaper\"}."
)


def judge_rule(
    client: object,
    *,
    provider: str = "openai",
    judge_model: str,
    response: str,
    rule: str,
) -> JudgeResult:
    patched = (
        instructor.from_anthropic(client)
        if provider == "anthropic"
        else instructor.from_openai(client, mode=instructor.Mode.TOOLS_STRICT)
    )
    t0 = time.perf_counter()
    try:
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
                max_retries=1,
            )
        else:
            verdict = patched.chat.completions.create(
                model=judge_model,
                response_model=JudgeVerdict,
                messages=messages,
                temperature=0,
                max_retries=1,
            )
        latency = int((time.perf_counter() - t0) * 1000)
        judge_input = JUDGE_SYSTEM + rule + response
        usage = Usage(estimate_tokens(judge_input), estimate_tokens(verdict.reasoning), estimated=True)
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
        return JudgeResult(
            rule=rule,
            passed=False,
            reasoning=f"judge error: {e}",
            latency_ms=latency,
            usage=Usage(),
            cost_usd=0.0,
        )

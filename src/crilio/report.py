from __future__ import annotations

import html
import pathlib
import xml.etree.ElementTree as ET
from typing import Any


def _esc(s: str) -> str:
    return html.escape(s)


def build_html(payload: dict[str, Any]) -> str:
    gate = payload.get("gate", "UNKNOWN")
    summary = payload.get("summary", {})
    tests = payload.get("tests", [])
    elapsed = payload.get("elapsed_s", 0)
    ts = payload.get("timestamp", "")
    sha = payload.get("git_sha") or ""
    branch = payload.get("git_branch") or ""
    color = "#16a34a" if gate == "PASS" else "#dc2626"
    rows = ""
    for t in tests:
        badge = '<span style="background:#16a34a;color:#fff;padding:2px 8px;border-radius:999px;font-size:12px">PASS</span>' if t.get("passed") else '<span style="background:#dc2626;color:#fff;padding:2px 8px;border-radius:999px;font-size:12px">FAIL</span>'
        rules_html = ""
        for r in t.get("rules", []):
            rc = "#16a34a" if r.get("passed") else "#dc2626"
            icon = "●"
            rules_html += f'<div style="display:flex;gap:8px;font-size:13px;margin:2px 0"><span style="color:{rc}">{icon}</span><span style="flex:1">{_esc(r.get("rule",""))}</span><span style="color:{rc};font-weight:700">{"PASS" if r.get("passed") else "FAIL"}</span></div>'
            if not r.get("passed") and r.get("reasoning"):
                rules_html += f'<div style="color:#a16207;font-size:12px;margin-left:16px">{_esc(r.get("reasoning","")[:200])}</div>'
        rows += f'<tr><td style="font-weight:700">{_esc(t.get("name",""))}</td><td style="color:#6b7280;max-width:280px;word-break:break-word">{_esc(t.get("prompt","")[:200])}</td><td style="max-width:320px;word-break:break-word">{_esc((t.get("response") or "")[:400])}</td><td>{badge}</td></tr>'
        if rules_html:
            rows += f'<tr><td colspan="4" style="background:#fafafa;padding:8px 12px">{rules_html}</td></tr>'

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crilio Report — {gate}</title>
<style>
body{{font-family:ui-sans,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;background:#fff;color:#111}}
header{{padding:24px 32px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}}
h1{{margin:0;font-size:20px}} .meta{{color:#6b7280;font-size:13px}}
.summary{{display:flex;gap:16px;padding:16px 32px;flex-wrap:wrap}}
.card{{border:1px solid #e5e7eb;border-radius:12px;padding:12px 16px;min-width:140px}}
table{{width:100%;border-collapse:collapse;margin:16px 32px;width:calc(100% - 64px)}}
th{{text-align:left;font-size:12px;letter-spacing:.06em;color:#6b7280;padding:8px;border-bottom:1px solid #eee}}
td{{padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;vertical-align:top}}
</style></head><body>
<header><h1>crilio <span style="color:{color}">Gate {gate}</span> <span style="font-weight:400;color:#6b7280">· {elapsed}s</span></h1><div class="meta">{_esc(ts)} {f"· {sha}" if sha else ""} {f"· {branch}" if branch else ""}</div></header>
<div class="summary">
<div class="card"><div style="font-size:12px;color:#6b7280">Rules</div><div style="font-size:20px;font-weight:800">{summary.get("passed",0)}/{summary.get("total",0)} passed</div></div>
<div class="card"><div style="font-size:12px;color:#6b7280">Cost</div><div style="font-size:20px;font-weight:800">${summary.get("cost_usd",0):.4f}</div></div>
<div class="card"><div style="font-size:12px;color:#6b7280">Tokens</div><div style="font-size:20px;font-weight:800">{summary.get("input_tokens",0)+summary.get("output_tokens",0):,}</div></div>
<div class="card"><div style="font-size:12px;color:#6b7280">Failed</div><div style="font-size:20px;font-weight:800;color:{color}">{summary.get("failed",0)}</div></div>
</div>
<table><thead><tr><th>Test</th><th>Prompt</th><th>Output</th><th>Verdict</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>"""


def build_junit(payload: dict[str, Any]) -> str:
    tests = payload.get("tests", [])
    total = sum(len(t.get("rules", [])) for t in tests)
    failures = sum(1 for t in tests for r in t.get("rules", []) if not r.get("passed"))
    suite = ET.Element("testsuite", name="crilio", tests=str(total), failures=str(failures))
    for t in tests:
        for r in t.get("rules", []):
            tc = ET.SubElement(suite, "testcase", classname=_sanitize(t.get("name","")), name=r.get("rule","")[:120])
            if not r.get("passed"):
                fail = ET.SubElement(tc, "failure", message=r.get("reasoning","")[:500])
                fail.text = f"Test: {t.get('name')}\nRule: {r.get('rule')}\nResponse: {(t.get('response') or '')[:500]}\nReason: {r.get('reasoning','')}"
    xml = ET.tostring(suite, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml


def _sanitize(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in s) or "test"


def write_report(payload: dict[str, Any], fmt: str, out: pathlib.Path) -> pathlib.Path:
    if fmt == "html":
        out.write_text(build_html(payload), encoding="utf-8")
    elif fmt == "junit":
        out.write_text(build_junit(payload), encoding="utf-8")
    else:
        raise ValueError(f"unknown format {fmt}")
    return out

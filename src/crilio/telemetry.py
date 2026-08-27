from __future__ import annotations

import os
import uuid
import pathlib

import requests

POSTHOG_HOST = "https://us.i.posthog.com"
POSTHOG_KEY = ""

def _distinct_id() -> str:
    if os.getenv("CRILIO_DISABLE_TELEMETRY") == "1" or os.getenv("DO_NOT_TRACK") == "1":
        return ""
    try:
        p = pathlib.Path.home() / ".config" / "crilio" / "telemetry_id"
        if p.exists():
            return p.read_text(encoding="utf-8").strip()[:64]
        nid = str(uuid.uuid4())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(nid, encoding="utf-8")
        return nid
    except Exception:
        return "crilio_anonymous"

def track(event: str, properties: dict | None = None):
    if os.getenv("CRILIO_DISABLE_TELEMETRY") == "1" or os.getenv("DO_NOT_TRACK") == "1":
        return
    key = os.getenv("POSTHOG_API_KEY", "")
    if not key:
        return
    host = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")
    try:
        distinct = _distinct_id()
        if not distinct:
            return
        payload = {
            "api_key": key,
            "event": event,
            "distinct_id": distinct,
            "properties": {
                "crilio_version": _crilio_version(),
                "python_version": _python_version(),
                "is_ci": os.getenv("GITHUB_ACTIONS") == "true",
                **(properties or {}),
            },
        }
        if os.getenv("CRILIO_TELEMETRY_DEBUG") == "1":
            import sys
            print(f"[telemetry] {host}/capture/ event={event} key={key[:8]}... distinct={distinct[:8]}", file=sys.stderr)
        resp = requests.post(f"{host}/capture/", json=payload, timeout=1)
        if os.getenv("CRILIO_TELEMETRY_DEBUG") == "1":
            import sys
            print(f"[telemetry] status={resp.status_code} body={resp.text[:200]}", file=sys.stderr)
    except Exception as e:
        if os.getenv("CRILIO_TELEMETRY_DEBUG") == "1":
            import sys
            print(f"[telemetry] error: {e}", file=sys.stderr)
        return

def _crilio_version() -> str:
    try:
        from crilio.__version__ import __version__
        return __version__
    except Exception:
        return "unknown"

def _python_version() -> str:
    import sys
    return f"{sys.version_info.major}.{sys.version_info.minor}"

"""
Sakura AI — Repeatable Demonstration Pre-Flight Health Check

Verifies backend liveness, deep readiness (DB + Alembic head revision),
capabilities truthfulness, frontend page reachability, and /_next/image hardening
before any college evaluation or technical interview demo.

Usage:
    python docs/demo_assets/preflight_check.py
    python docs/demo_assets/preflight_check.py --backend http://127.0.0.1:8000 --frontend http://127.0.0.1:3000
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


def fetch(url: str, timeout: int = 10):
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore")
    except Exception as exc:
        return 0, str(exc)


def main():
    parser = argparse.ArgumentParser(description="Sakura AI Demo Pre-Flight Check")
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend", default="http://127.0.0.1:3000")
    args = parser.parse_args()

    backend = args.backend.rstrip("/")
    frontend = args.frontend.rstrip("/")
    failed = 0

    def check(label: str, ok: bool, detail: str):
        nonlocal failed
        tag = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{tag}] {label}: {detail}")

    # 1. Backend /health
    code, body = fetch(f"{backend}/health")
    check("Backend /health", code == 200, f"HTTP {code} {body[:120]}")

    # 2. Backend /readiness
    code, body = fetch(f"{backend}/readiness")
    rd = {}
    if code == 200:
        try:
            rd = json.loads(body)
        except Exception:
            pass
    check(
        "Backend /readiness",
        code == 200 and rd.get("database") == "CONNECTED" and rd.get("schema_migrated") is True,
        f"HTTP {code} status={rd.get('status')} db={rd.get('database')} rev={rd.get('schema_revision')} redis={rd.get('redis')}",
    )

    # 3. Backend /api/v1/capabilities
    code, body = fetch(f"{backend}/api/v1/capabilities")
    cap = {}
    if code == 200:
        try:
            cap = json.loads(body)
        except Exception:
            pass
    check(
        "Backend /api/v1/capabilities",
        code == 200,
        f"HTTP {code} env={cap.get('environment')} sandbox={cap.get('sandbox', {}).get('runtime')}",
    )

    # 4. Frontend key pages
    for route in ["/", "/login", "/about", "/features"]:
        code, body = fetch(f"{frontend}{route}")
        check(f"Frontend GET {route}", code == 200, f"HTTP {code} ({len(body)} bytes)")

    # 5. Next.js /_next/image hardening check
    code, _ = fetch(f"{frontend}/_next/image?url=%2Ffavicon.ico&w=64&q=75")
    check("Frontend /_next/image disabled", code in (400, 404), f"HTTP {code}")

    # 6. Proxy reachability
    code, _ = fetch(f"{frontend}/api/v1/capabilities")
    check("Frontend -> Backend proxy", code == 200, f"HTTP {code}")

    print(f"\nPRE-FLIGHT RESULT: {'READY FOR DEMO' if failed == 0 else f'{failed} CHECK(S) FAILED'}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

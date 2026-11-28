"""
Sakura AI — Isolated Killable Subprocess Runner for Storage Deletion Outbox

Invoked as: `python -m services.storage_delete_runner`
Reads a single JSON object from stdin:
  {"entry": {...}, "timeout_seconds": 60.0}
Executes the physical storage deletion with bounded timeouts and writes a single
JSON result line to stdout:
  {"ok": true, "error": null}

Running physical storage deletion in a dedicated OS subprocess guarantees that
when the parent worker hits a timeout, loses its DB lease, or is cancelled,
SIGTERM/SIGKILL + wait() definitively terminates the operation so it can NEVER
continue mutating storage after the claim is dropped or reassigned.
"""

import json
import os
import sys


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            sys.stdout.write(json.dumps({"ok": False, "error": "Empty storage deletion runner payload"}) + "\n")
            sys.stdout.flush()
            return 1

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"ok": False, "error": f"Malformed JSON payload: {exc}"}) + "\n")
            sys.stdout.flush()
            return 1

        if not isinstance(payload, dict):
            sys.stdout.write(json.dumps({"ok": False, "error": "Runner payload must be a JSON object"}) + "\n")
            sys.stdout.flush()
            return 1

        entry = payload.get("entry")
        if not isinstance(entry, dict) or (not entry.get("storage_key") and not entry.get("legacy_path")):
            sys.stdout.write(
                json.dumps({"ok": False, "error": "Runner entry must be an object with storage_key or legacy_path"}) + "\n"
            )
            sys.stdout.flush()
            return 1

        timeout_seconds = payload.get("timeout_seconds")
        delay_seconds = payload.get("test_delay_seconds")

        env_name = os.getenv("ENVIRONMENT", "development").strip().lower()
        if delay_seconds is not None and env_name not in ("production", "prod"):
            delay_val = float(delay_seconds)
            if delay_val > 0:
                import time
                time.sleep(delay_val)

        from services.documents import _execute_outbox_physical_deletion

        ok, err = _execute_outbox_physical_deletion(
            entry,
            storage_override=None,
            timeout_seconds=float(timeout_seconds) if timeout_seconds is not None else None,
        )
        sys.stdout.write(json.dumps({"ok": bool(ok), "error": err}) + "\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}) + "\n")
        sys.stdout.flush()
        return 1


if __name__ == "__main__":
    # Ensure backend root is on sys.path
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    sys.exit(main())

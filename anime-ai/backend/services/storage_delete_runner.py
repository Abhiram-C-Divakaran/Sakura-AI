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
        payload = json.loads(raw) if raw.strip() else {}
        entry = payload.get("entry") or {}
        timeout_seconds = payload.get("timeout_seconds")
        delay_seconds = payload.get("test_delay_seconds")

        if delay_seconds is not None and float(delay_seconds) > 0:
            import time
            time.sleep(float(delay_seconds))

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
        return 0


if __name__ == "__main__":
    # Ensure backend root is on sys.path
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    sys.exit(main())

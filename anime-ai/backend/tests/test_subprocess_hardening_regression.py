"""
Sakura AI — Subprocess Execution, Termination, Pipe-Safety & Cleanup Regression Suite

Covers:
1. Commands exceeding their timeout (outbox runner & LocalRestrictedSandboxRuntime).
2. Child-process termination and cleanup (verified dead PIDs, no lingering processes).
3. Process-tree termination (child spawning a long-lived grandchild -> both killed).
4. Non-zero exit codes (even when stdout emits {"ok": true} -> MUST fail closed).
5. Large stdout/stderr output (>128 KiB each -> zero pipe deadlock, bounded capture).
6. Malformed input (empty stdin, invalid JSON, non-object JSON, missing keys) and malformed stdout.
7. Cancellation during execution (asyncio cancellation & worker_cancel_event + stale-lease fence).
8. Temporary directory and resource cleanup.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_anime_ai.db")
os.environ["ENVIRONMENT"] = "test"
os.environ["SAKURA_EMBEDDED_WORKER"] = "false"
os.environ["SAKURA_EMBEDDED_SCHEDULER"] = "false"
os.environ["SAKURA_EMBEDDED_CODING_WORKER"] = "false"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from auth.manager import AuthManager
from coding.sandbox import LocalRestrictedSandboxRuntime
from database.db import Base, engine, get_db_context
from database.models import Document, StorageDeletionOutbox, User, utc_now
from services.documents import (
    _run_leased_outbox_deletion_subprocess,
    claim_storage_deletion_outbox_entries,
    process_storage_deletion_outbox,
)
from services.storage import LocalFilesystemStorage


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _make_user(db, prefix="subp"):
    uid = uuid.uuid4()
    u = User(
        id=uid,
        username=f"{prefix}_{uid.hex[:8]}@example.com",
        email=f"{prefix}_{uid.hex[:8]}@example.com",
        hashed_password=AuthManager.hash_password("StrongPass123!"),
        created_at=utc_now(),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class TestSubprocessHardeningRegression(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="sakura_subproc_reg_")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _run_storage_runner_direct(self, stdin_text: str, env_overrides=None):
        env = dict(os.environ)
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, "-m", "services.storage_delete_runner"],
            input=stdin_text,
            capture_output=True,
            text=True,
            cwd=BACKEND_DIR,
            env=env,
            timeout=15,
        )

    def test_storage_delete_runner_rejects_malformed_and_empty_inputs(self):
        """Empty stdin, invalid JSON, non-dict JSON, and empty entry MUST exit non-zero with ok=False."""
        bad_payloads = [
            "",
            "   \n",
            "{not valid json",
            "[]",
            '"just a string"',
            json.dumps({}),
            json.dumps({"entry": {}}),
            json.dumps({"entry": {"storage_backend": "local", "storage_key": "", "legacy_path": None}}),
        ]
        for raw in bad_payloads:
            res = self._run_storage_runner_direct(raw)
            self.assertNotEqual(res.returncode, 0, f"Malformed payload unexpectedly returned 0: {raw!r}")
            lines = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
            self.assertTrue(lines, f"Expected JSON error line for payload {raw!r}")
            parsed = json.loads(lines[-1])
            self.assertFalse(parsed.get("ok"), f"Malformed payload MUST NOT report ok=True: {raw!r}")
            self.assertTrue(parsed.get("error"), f"Expected actionable error for payload {raw!r}")

    def test_storage_delete_runner_ignores_test_delay_in_production(self):
        """Production runner MUST NOT honor test_delay_seconds to stall workers."""
        local_store = LocalFilesystemStorage(root_dir=self.tmp_dir)
        uid = uuid.uuid4()
        key = f"users/{uid}/documents/{uuid.uuid4()}/fast_prod.txt"
        local_store.put(key, b"payload", content_type="text/plain", user_id=uid)

        payload = json.dumps(
            {
                "entry": {"storage_backend": "local", "storage_key": key, "legacy_path": None},
                "timeout_seconds": 10.0,
                "test_delay_seconds": 10.0,
            }
        )
        t0 = time.monotonic()
        res = self._run_storage_runner_direct(
            payload,
            env_overrides={"ENVIRONMENT": "production", "SAKURA_STORAGE_ROOT": self.tmp_dir},
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertLess(elapsed, 4.0, f"Production runner honored test_delay_seconds ({elapsed:.2f}s)!")
        self.assertFalse(local_store.exists(key))

    def test_outbox_subprocess_handles_large_stdout_and_stderr_without_pipe_deadlock(self):
        """
        Subprocess emitting >128 KiB on BOTH stdout and stderr before outputting final JSON
        must NOT deadlock OS pipe buffers and must finalize cleanly.
        """
        real_popen = subprocess.Popen
        helper_code = (
            "import json, sys; "
            "_ = sys.stdin.read(); "
            "sys.stdout.write('O' * 160000 + '\\n'); "
            "sys.stderr.write('E' * 160000 + '\\n'); "
            "sys.stdout.write(json.dumps({'ok': True, 'error': None}) + '\\n'); "
            "sys.stdout.flush()"
        )

        def _noisy_popen(args, **kwargs):
            return real_popen([sys.executable, "-c", helper_code], **kwargs)

        with get_db_context() as db:
            user = _make_user(db, "noisy_sub")
            oid = uuid.uuid4()
            db.add(
                StorageDeletionOutbox(
                    id=oid,
                    user_id=user.id,
                    storage_backend="local",
                    storage_key=f"users/{user.id}/noisy.txt",
                    status="PENDING",
                    attempt_count=0,
                    max_attempts=5,
                    next_retry_at=utc_now() - timedelta(seconds=1),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            db.commit()

            claimed = claim_storage_deletion_outbox_entries(db, worker_id="noisy_worker", limit=5, lease_seconds=10.0)
            target = next(c for c in claimed if c["id"] == oid)

            with patch("subprocess.Popen", side_effect=_noisy_popen):
                res = _run_leased_outbox_deletion_subprocess(
                    session=db,
                    entry=target,
                    worker_id="noisy_worker",
                    effective_lease=10.0,
                    effective_renew=3.0,
                    effective_timeout=5.0,
                    effective_grace=1.0,
                )

            self.assertEqual(res["outcome"], "completed", f"Large output caused failure/deadlock: {res}")
            self.assertFalse(res["subprocess_terminated"])

    def test_outbox_subprocess_nonzero_exit_never_reports_success_even_with_ok_json(self):
        """Non-zero exit code MUST ALWAYS fail closed even if stdout printed {'ok': true}."""
        real_popen = subprocess.Popen
        helper_code = (
            "import json, sys; "
            "_ = sys.stdin.read(); "
            "sys.stdout.write(json.dumps({'ok': True, 'error': None}) + '\\n'); "
            "sys.stderr.write('fatal crash after stdout\\n'); "
            "sys.exit(2)"
        )

        def _crashing_popen(args, **kwargs):
            return real_popen([sys.executable, "-c", helper_code], **kwargs)

        with get_db_context() as db:
            user = _make_user(db, "nz_sub")
            doc_id = uuid.uuid4()
            oid = uuid.uuid4()
            db.add(
                Document(
                    id=doc_id,
                    user_id=user.id,
                    filename="nz.txt",
                    mime_type="text/plain",
                    storage_path=f"users/{user.id}/nz.txt",
                    storage_key=f"users/{user.id}/nz.txt",
                    storage_backend="local",
                )
            )
            db.add(
                StorageDeletionOutbox(
                    id=oid,
                    user_id=user.id,
                    document_id=doc_id,
                    storage_backend="local",
                    storage_key=f"users/{user.id}/nz.txt",
                    status="PENDING",
                    attempt_count=0,
                    max_attempts=5,
                    next_retry_at=utc_now() - timedelta(seconds=1),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            db.commit()

            claimed = claim_storage_deletion_outbox_entries(db, worker_id="nz_worker", limit=5, lease_seconds=10.0)
            target = next(c for c in claimed if c["id"] == oid)

            with patch("subprocess.Popen", side_effect=_crashing_popen):
                res = _run_leased_outbox_deletion_subprocess(
                    session=db,
                    entry=target,
                    worker_id="nz_worker",
                    effective_lease=10.0,
                    effective_renew=3.0,
                    effective_timeout=5.0,
                    effective_grace=1.0,
                )

            self.assertEqual(res["outcome"], "retried")
            self.assertIn("fatal crash", res["error"] or "")
            # Document MUST still exist (never falsely deleted on non-zero exit!)
            doc_after = db.query(Document).filter(Document.id == doc_id).first()
            self.assertIsNotNone(doc_after)
            self.assertEqual(doc_after.deletion_status, "DELETE_FAILED")

    def test_outbox_subprocess_malformed_stdout_never_reports_success(self):
        """Malformed or missing JSON on stdout MUST fail closed and retain Document."""
        real_popen = subprocess.Popen
        helper_code = "import sys; _ = sys.stdin.read(); print('not-json-at-all'); print('{\"not_ok_key\": 123}')"

        def _bad_out_popen(args, **kwargs):
            return real_popen([sys.executable, "-c", helper_code], **kwargs)

        with get_db_context() as db:
            user = _make_user(db, "badout_sub")
            oid = uuid.uuid4()
            db.add(
                StorageDeletionOutbox(
                    id=oid,
                    user_id=user.id,
                    storage_backend="local",
                    storage_key=f"users/{user.id}/badout.txt",
                    status="PENDING",
                    attempt_count=0,
                    max_attempts=5,
                    next_retry_at=utc_now() - timedelta(seconds=1),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            db.commit()

            claimed = claim_storage_deletion_outbox_entries(db, worker_id="badout_w", limit=5, lease_seconds=10.0)
            target = next(c for c in claimed if c["id"] == oid)

            with patch("subprocess.Popen", side_effect=_bad_out_popen):
                res = _run_leased_outbox_deletion_subprocess(
                    session=db,
                    entry=target,
                    worker_id="badout_w",
                    effective_lease=10.0,
                    effective_renew=3.0,
                    effective_timeout=5.0,
                    effective_grace=1.0,
                )

            self.assertEqual(res["outcome"], "retried")
            self.assertIn("malformed", (res["error"] or "").lower())

    def test_outbox_subprocess_timeout_terminates_entire_process_tree(self):
        """
        Child process spawns a long-lived grandchild; on timeout, BOTH child and grandchild
        MUST be terminated and reaped so zero orphaned processes remain.
        """
        real_popen = subprocess.Popen
        pid_file = os.path.join(self.tmp_dir, "grandchild.pid")
        child_pid_file = os.path.join(self.tmp_dir, "child.pid")

        spawner_code = (
            "import os, subprocess, sys, time; "
            "_ = sys.stdin.read(); "
            f"open({child_pid_file!r}, 'w').write(str(os.getpid())); "
            "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
            f"open({pid_file!r}, 'w').write(str(gc.pid)); "
            "time.sleep(60)"
        )

        def _tree_popen(args, **kwargs):
            return real_popen([sys.executable, "-c", spawner_code], **kwargs)

        with get_db_context() as db:
            user = _make_user(db, "tree_sub")
            oid = uuid.uuid4()
            db.add(
                StorageDeletionOutbox(
                    id=oid,
                    user_id=user.id,
                    storage_backend="local",
                    storage_key=f"users/{user.id}/tree.txt",
                    status="PENDING",
                    attempt_count=0,
                    max_attempts=5,
                    next_retry_at=utc_now() - timedelta(seconds=1),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            db.commit()

            claimed = claim_storage_deletion_outbox_entries(db, worker_id="tree_worker", limit=5, lease_seconds=10.0)
            target = next(c for c in claimed if c["id"] == oid)

            with patch("subprocess.Popen", side_effect=_tree_popen):
                res = _run_leased_outbox_deletion_subprocess(
                    session=db,
                    entry=target,
                    worker_id="tree_worker",
                    effective_lease=10.0,
                    effective_renew=2.0,
                    effective_timeout=0.8,
                    effective_grace=0.25,
                )

            self.assertTrue(res["subprocess_terminated"])
            self.assertEqual(res["outcome"], "retried")

        # Give OS a short moment to finalize process teardown
        time.sleep(0.35)
        self.assertTrue(os.path.exists(child_pid_file), "Child PID file was not written")
        self.assertTrue(os.path.exists(pid_file), "Grandchild PID file was not written")
        with open(child_pid_file, "r", encoding="utf-8") as f:
            child_pid = int(f.read().strip())
        with open(pid_file, "r", encoding="utf-8") as f:
            grandchild_pid = int(f.read().strip())
        self.assertFalse(_pid_is_alive(child_pid), f"Child process {child_pid} leaked after timeout!")
        self.assertFalse(_pid_is_alive(grandchild_pid), f"Grandchild process {grandchild_pid} leaked after timeout!")

    def test_outbox_subprocess_cancelled_after_lease_expiry_returns_stale_without_overwriting(self):
        """A worker cancelled AFTER its lease expired MUST NOT overwrite another worker's claim."""
        with patch.dict(os.environ, {"SAKURA_STORAGE_ROOT": self.tmp_dir}):
            with get_db_context() as db:
                user = _make_user(db, "stale_cancel")
                oid = uuid.uuid4()
                db.add(
                    StorageDeletionOutbox(
                        id=oid,
                        user_id=user.id,
                        storage_backend="local",
                        storage_key=f"users/{user.id}/stale_cancel.txt",
                        status="PENDING",
                        attempt_count=0,
                        max_attempts=5,
                        next_retry_at=utc_now() - timedelta(seconds=1),
                        created_at=utc_now(),
                        updated_at=utc_now(),
                    )
                )
                db.commit()

                claimed = claim_storage_deletion_outbox_entries(db, worker_id="old_w", limit=5, lease_seconds=5.0)
                target = next(c for c in claimed if c["id"] == oid)

                # Expire the lease BEFORE worker_cancel_event triggers
                db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == oid).update(
                    {StorageDeletionOutbox.lease_expires_at: utc_now() - timedelta(seconds=5)},
                    synchronize_session=False,
                )
                db.commit()

                cancel_ev = threading.Event()
                timer = threading.Timer(0.15, cancel_ev.set)
                timer.start()
                try:
                    res = _run_leased_outbox_deletion_subprocess(
                        session=db,
                        entry=target,
                        worker_id="old_w",
                        effective_lease=5.0,
                        effective_renew=5.0,
                        effective_timeout=5.0,
                        effective_grace=0.2,
                        worker_cancel_event=cancel_ev,
                        subprocess_test_delay_seconds=5.0,
                    )
                finally:
                    timer.cancel()

                self.assertEqual(res["outcome"], "stale")
                self.assertTrue(res["subprocess_terminated"])
                # Row MUST NOT have been reset to PENDING by the expired worker!
                row = db.query(StorageDeletionOutbox).filter(StorageDeletionOutbox.id == oid).first()
                self.assertEqual(row.status, "PROCESSING")
                # Clean up
                row.status = "COMPLETED"
                row.lease_expires_at = None
                db.commit()

    async def test_local_sandbox_timeout_cancellation_nonzero_large_output_and_tree_cleanup(self):
        """
        Verifies LocalRestrictedSandboxRuntime subprocess contract:
        - non-zero exit code -> success=False with exact exit code
        - large stdout/stderr -> bounded truncation without hang
        - timeout -> kills entire process tree (child + grandchild)
        - asyncio cancellation -> kills process tree and propagates CancelledError
        """
        ws = tempfile.mkdtemp(prefix="sakura_sb_subproc_")
        try:
            rt = LocalRestrictedSandboxRuntime(workspace_root=ws, default_timeout_seconds=10)

            # 1. Non-zero exit code
            res_nz = await rt.run_command([sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(7)"])
            self.assertFalse(res_nz["success"])
            self.assertEqual(res_nz["exit_code"], 7)
            self.assertIn("out", res_nz["stdout"])
            self.assertIn("err", res_nz["stderr"])

            # 2. Large stdout/stderr (>150 KiB) truncated to MAX_OUTPUT_CHARS without hang
            res_big = await rt.run_command(
                [sys.executable, "-c", "import sys; sys.stdout.write('A' * 150000); sys.stderr.write('B' * 150000)"]
            )
            self.assertTrue(res_big["success"])
            self.assertEqual(len(res_big["stdout"]), rt.MAX_OUTPUT_CHARS)
            self.assertEqual(len(res_big["stderr"]), rt.MAX_OUTPUT_CHARS)

            # 3. Timeout kills child + grandchild process tree
            gc_pid_file = os.path.join(ws, "sb_gc.pid")
            tree_script = (
                "import subprocess, sys, time; "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                f"open({gc_pid_file!r}, 'w').write(str(p.pid)); "
                "time.sleep(60)"
            )
            res_to = await rt.run_command([sys.executable, "-c", tree_script], timeout_seconds=1)
            self.assertFalse(res_to["success"])
            self.assertTrue(res_to["timed_out"])
            time.sleep(0.3)
            if os.path.exists(gc_pid_file):
                with open(gc_pid_file, "r", encoding="utf-8") as f:
                    gc_pid = int(f.read().strip())
                self.assertFalse(_pid_is_alive(gc_pid), f"Sandbox grandchild PID {gc_pid} leaked after timeout!")

            # 4. Asyncio cancellation kills child + grandchild and propagates CancelledError
            gc_cancel_file = os.path.join(ws, "sb_gc_cancel.pid")
            cancel_script = (
                "import subprocess, sys, time; "
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                f"open({gc_cancel_file!r}, 'w').write(str(p.pid)); "
                "time.sleep(60)"
            )
            task = asyncio.create_task(rt.run_command([sys.executable, "-c", cancel_script], timeout_seconds=30))
            await asyncio.sleep(0.45)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            time.sleep(0.3)
            if os.path.exists(gc_cancel_file):
                with open(gc_cancel_file, "r", encoding="utf-8") as f:
                    gc_cpid = int(f.read().strip())
                self.assertFalse(_pid_is_alive(gc_cpid), f"Sandbox grandchild PID {gc_cpid} leaked after cancel!")
        finally:
            shutil.rmtree(ws, ignore_errors=True)
            self.assertFalse(os.path.exists(ws))


if __name__ == "__main__":
    unittest.main()

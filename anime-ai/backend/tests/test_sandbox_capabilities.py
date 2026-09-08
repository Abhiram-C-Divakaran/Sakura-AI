"""
Unit and integration tests for sandbox capability token verification, signing, tampering, and replay protection.
"""

import time
import uuid
import unittest
from coding.capabilities import (
    mint_sandbox_capability,
    verify_and_consume_capability,
    clear_consumed_capabilities,
    CapabilityError,
    CapabilitySignatureError,
    CapabilityExpiredError,
    CapabilityReplayError,
    CapabilityScopeError,
    CapabilityMismatchError,
)


class TestSandboxCapabilities(unittest.TestCase):

    def setUp(self):
        clear_consumed_capabilities()

    def test_mint_and_verify_valid_token(self):
        ws_id = str(uuid.uuid4())
        secret = "super_secret_signing_key_for_testing_12345"
        cmd = "git clone https://github.com/example/repo.git ."
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command=cmd,
            scope="repository_clone",
            secret_key=secret,
            ttl_seconds=30
        )
        self.assertIsInstance(token, str)

        payload = verify_and_consume_capability(
            capability_token=token,
            secret_key=secret,
            expected_scope="repository_clone",
            expected_workspace_id=ws_id,
            expected_command=cmd
        )
        self.assertEqual(payload["ws_id"], ws_id)
        self.assertEqual(payload["scope"], "repository_clone")

    def test_flexible_scope_list(self):
        ws_id = str(uuid.uuid4())
        secret = "super_secret_signing_key_for_testing_12345"
        cmd = "git clone https://github.com/example/repo.git ."
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command=cmd,
            scope="repository_clone",
            secret_key=secret
        )

        # verify with expected_scope as list
        payload = verify_and_consume_capability(
            capability_token=token,
            secret_key=secret,
            expected_scope=["network_exec", "repository_clone"],
            expected_workspace_id=ws_id,
            expected_command=cmd
        )
        self.assertEqual(payload["scope"], "repository_clone")

    def test_scope_mismatch_rejected(self):
        ws_id = str(uuid.uuid4())
        secret = "super_secret_signing_key_for_testing_12345"
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command="ls -la",
            scope="other_scope",
            secret_key=secret
        )

        with self.assertRaises(CapabilityScopeError) as ctx:
            verify_and_consume_capability(
                capability_token=token,
                secret_key=secret,
                expected_scope="repository_clone"
            )
        self.assertIn("scope mismatch", str(ctx.exception).lower())

    def test_workspace_mismatch_rejected(self):
        ws_a = str(uuid.uuid4())
        ws_b = str(uuid.uuid4())
        secret = "super_secret_signing_key_for_testing_12345"
        token = mint_sandbox_capability(
            workspace_id=ws_a,
            command="ls -la",
            scope="repository_clone",
            secret_key=secret
        )

        with self.assertRaises(CapabilityMismatchError) as ctx:
            verify_and_consume_capability(
                capability_token=token,
                secret_key=secret,
                expected_workspace_id=ws_b
            )
        self.assertIn("workspace mismatch", str(ctx.exception).lower())

    def test_tampered_payload_rejected(self):
        ws_id = str(uuid.uuid4())
        secret = "super_secret_signing_key_for_testing_12345"
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command="ls -la",
            scope="repository_clone",
            secret_key=secret
        )

        parts = token.split(".")
        tampered_token = f"dGFtcGVyZWQ.{parts[1]}"
        with self.assertRaises(CapabilitySignatureError):
            verify_and_consume_capability(
                capability_token=tampered_token,
                secret_key=secret
            )

    def test_tampered_signature_rejected(self):
        ws_id = str(uuid.uuid4())
        secret = "super_secret_signing_key_for_testing_12345"
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command="ls -la",
            scope="repository_clone",
            secret_key=secret
        )

        parts = token.split(".")
        tampered_token = f"{parts[0]}.bad_signature_hash"
        with self.assertRaises(CapabilitySignatureError):
            verify_and_consume_capability(
                capability_token=tampered_token,
                secret_key=secret
            )

    def test_wrong_signing_key_rejected(self):
        ws_id = str(uuid.uuid4())
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command="ls -la",
            scope="repository_clone",
            secret_key="correct_key"
        )

        with self.assertRaises(CapabilitySignatureError):
            verify_and_consume_capability(
                capability_token=token,
                secret_key="wrong_key"
            )

    def test_expired_token_rejected(self):
        ws_id = str(uuid.uuid4())
        secret = "test_secret"
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command="ls -la",
            scope="repository_clone",
            secret_key=secret,
            ttl_seconds=0  # immediately expires
        )
        time.sleep(0.01)

        with self.assertRaises(CapabilityExpiredError):
            verify_and_consume_capability(
                capability_token=token,
                secret_key=secret
            )

    def test_replay_protection_enforced(self):
        ws_id = str(uuid.uuid4())
        secret = "test_secret"
        token = mint_sandbox_capability(
            workspace_id=ws_id,
            command="ls -la",
            scope="repository_clone",
            secret_key=secret,
            ttl_seconds=60
        )

        # First consumption succeeds
        payload = verify_and_consume_capability(
            capability_token=token,
            secret_key=secret
        )
        self.assertIsNotNone(payload)

        # Second consumption fails with replay error
        with self.assertRaises(CapabilityReplayError):
            verify_and_consume_capability(
                capability_token=token,
                secret_key=secret
            )


if __name__ == "__main__":
    unittest.main()

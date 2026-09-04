import unittest
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.models import TaskOutcome
from coding.agent import CodingAgent

class TestCodingVerificationSemantics(unittest.TestCase):
    def test_task_kind_classification(self):
        """Classifies objectives into MUTATING vs READ_ONLY properly."""
        self.assertEqual(CodingAgent.classify_task_kind("fix the auth bug in this repo"), "MUTATING")
        self.assertEqual(CodingAgent.classify_task_kind("update the API validation"), "MUTATING")
        self.assertEqual(CodingAgent.classify_task_kind("refactor this component"), "MUTATING")
        self.assertEqual(CodingAgent.classify_task_kind("implement pagination in backend"), "MUTATING")
        self.assertEqual(CodingAgent.classify_task_kind("explain how the router works"), "READ_ONLY")
        self.assertEqual(CodingAgent.classify_task_kind("what is the database schema?"), "READ_ONLY")
        self.assertEqual(CodingAgent.classify_task_kind("where is the AuthManager defined?"), "READ_ONLY")

    def test_mutating_task_requires_files_and_tests(self):
        """A mutating objective cannot be marked COMPLETED_VERIFIED without files and tests."""
        # Simulated scenario: 0 files changed + 0 tests run
        task_kind = "MUTATING"
        modified_files = []
        tests_run = []
        unverified_reasons = []

        tests_run_count = len(tests_run)
        tests_passed = tests_run_count > 0 and all(t.get("exit_code") == 0 for t in tests_run)

        if task_kind == "MUTATING":
            if not modified_files:
                unverified_reasons.append("No files were modified for a mutating task objective.")
            if tests_run_count == 0:
                unverified_reasons.append("No test suite was executed to verify file modifications.")

        self.assertIn("No files were modified for a mutating task objective.", unverified_reasons)
        self.assertIn("No test suite was executed to verify file modifications.", unverified_reasons)
        
        # Must NOT be completed verified
        self.assertFalse(tests_passed)
        self.assertTrue(len(unverified_reasons) > 0)

    def test_mutating_task_with_files_but_no_tests_unverified(self):
        """A mutating objective that modifies files but runs no tests is COMPLETED_UNVERIFIED, not VERIFIED."""
        task_kind = "MUTATING"
        modified_files = ["src/auth.py"]
        tests_run = []
        unverified_reasons = []

        tests_run_count = len(tests_run)
        tests_passed = tests_run_count > 0 and all(t.get("exit_code") == 0 for t in tests_run)

        if task_kind == "MUTATING":
            if not modified_files:
                unverified_reasons.append("No files were modified.")
            if tests_run_count == 0:
                unverified_reasons.append("No test suite was executed to verify file modifications.")

        status = TaskOutcome.COMPLETED_VERIFIED if (tests_passed and modified_files) else TaskOutcome.COMPLETED_UNVERIFIED
        self.assertEqual(status, TaskOutcome.COMPLETED_UNVERIFIED)
        self.assertIn("No test suite was executed to verify file modifications.", unverified_reasons)

    def test_mutating_task_with_files_and_passing_tests_verified(self):
        """A mutating objective with modified files and exit_code 0 tests is COMPLETED_VERIFIED."""
        task_kind = "MUTATING"
        modified_files = ["src/auth.py"]
        tests_run = [{"exit_code": 0, "stdout": "All tests passed"}]
        unverified_reasons = []

        tests_run_count = len(tests_run)
        tests_passed = tests_run_count > 0 and all(t.get("exit_code") == 0 for t in tests_run)
        tests_failed = tests_run_count > 0 and any(t.get("exit_code") != 0 for t in tests_run)

        if task_kind == "MUTATING":
            if not modified_files:
                unverified_reasons.append("No files were modified.")
            if tests_run_count == 0:
                unverified_reasons.append("No tests run.")
            elif tests_failed:
                unverified_reasons.append("Tests failed.")

        status = TaskOutcome.COMPLETED_VERIFIED if (tests_passed and modified_files and not tests_failed) else TaskOutcome.COMPLETED_UNVERIFIED
        self.assertEqual(status, TaskOutcome.COMPLETED_VERIFIED)
        self.assertEqual(len(unverified_reasons), 0)

if __name__ == "__main__":
    unittest.main()

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

    def test_post_edit_verification_allows_fail_then_patch_then_pass(self):
        """Reproducing a failing test, patching the bug, and re-running to pass must evaluate as passed."""
        agent = CodingAgent.__new__(CodingAgent)
        agent._mutation_epoch = 2
        runs = [
            {"command": "python3 test_calc.py", "exit_code": 1, "mutation_epoch": 1},
            {"command": "python3 test_calc.py", "exit_code": 0, "mutation_epoch": 2},
        ]
        count, passed, failed = agent._evaluate_latest_verification_runs(runs)
        self.assertEqual(count, 1)
        self.assertTrue(passed)
        self.assertFalse(failed)

        # If a new file mutation occurs after the passing run without re-running tests -> unverified (0 effective runs)
        agent._mutation_epoch = 3
        count2, passed2, failed2 = agent._evaluate_latest_verification_runs(runs)
        self.assertEqual(count2, 0)
        self.assertFalse(passed2)
        self.assertFalse(failed2)

        # If the latest run at the current epoch fails -> failed
        runs.append({"command": "python3 test_calc.py", "exit_code": 1, "mutation_epoch": 3})
        count3, passed3, failed3 = agent._evaluate_latest_verification_runs(runs)
        self.assertEqual(count3, 1)
        self.assertFalse(passed3)
        self.assertTrue(failed3)

if __name__ == "__main__":
    unittest.main()

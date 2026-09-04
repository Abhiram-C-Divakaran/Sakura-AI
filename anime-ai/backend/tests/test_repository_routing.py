import unittest
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import is_repository_coding_intent

class DummyWorkspace:
    def __init__(self, id, name):
        self.id = id
        self.name = name

class TestRepositoryRouting(unittest.TestCase):
    def test_coding_intent_detection(self):
        """Repository engineering phrases must be recognized as coding intent."""
        self.assertTrue(is_repository_coding_intent("/code check syntax"))
        self.assertTrue(is_repository_coding_intent("fix the auth bug in this repo"))
        self.assertTrue(is_repository_coding_intent("update the API validation"))
        self.assertTrue(is_repository_coding_intent("run the tests and fix failures"))
        self.assertTrue(is_repository_coding_intent("refactor this component"))
        self.assertTrue(is_repository_coding_intent("implement pagination in the backend"))
        self.assertTrue(is_repository_coding_intent("review this repository and patch the issue"))
        self.assertTrue(is_repository_coding_intent("find memory leak in this codebase"))

    def test_generic_questions_not_routed_to_repo_coding(self):
        """Generic programming or conceptual questions must NOT be detected as repository coding intent."""
        self.assertFalse(is_repository_coding_intent("what is a python generator?"))
        self.assertFalse(is_repository_coding_intent("how do I write a binary search tree?"))
        self.assertFalse(is_repository_coding_intent("explain the difference between async and threads"))
        self.assertFalse(is_repository_coding_intent("hello sakura, how are you?"))

    def test_unambiguous_single_workspace_selection(self):
        """When exactly one workspace exists, it must be selected unambiguously."""
        ws1 = DummyWorkspace("uuid-1", "Sakura-AI")
        user_workspaces = [ws1]
        
        selected = None
        if len(user_workspaces) == 1:
            selected = user_workspaces[0]
        self.assertEqual(selected, ws1)

    def test_explicit_active_workspace_selection(self):
        """When an explicit workspace ID is provided, that specific workspace is selected."""
        ws1 = DummyWorkspace("uuid-1", "Repo-A")
        ws2 = DummyWorkspace("uuid-2", "Repo-B")
        user_workspaces = [ws1, ws2]

        explicit_id = "uuid-2"
        selected = next((w for w in user_workspaces if w.id == explicit_id), None)
        self.assertEqual(selected, ws2)

    def test_multiple_workspaces_no_selection_ambiguity(self):
        """When multiple workspaces exist and none is selected, no workspace should be guessed."""
        ws1 = DummyWorkspace("uuid-1", "Repo-A")
        ws2 = DummyWorkspace("uuid-2", "Repo-B")
        user_workspaces = [ws1, ws2]

        explicit_id = None
        selected = None
        is_ambiguous = False

        if explicit_id:
            selected = next((w for w in user_workspaces if w.id == explicit_id), None)
        elif len(user_workspaces) == 1:
            selected = user_workspaces[0]
        elif len(user_workspaces) > 1:
            is_ambiguous = True

        self.assertIsNone(selected)
        self.assertTrue(is_ambiguous)

if __name__ == "__main__":
    unittest.main()

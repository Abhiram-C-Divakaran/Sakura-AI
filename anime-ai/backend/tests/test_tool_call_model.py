import unittest
import os
import sys
import json

os.environ["DATABASE_URL"] = "sqlite:///./test_anime_ai.db"
os.environ["ENVIRONMENT"] = "test"
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.providers.anthropic import AnthropicProvider
from llm.providers.openai import OpenAIProvider

class DummyAnthropicClient:
    pass

class DummyOpenAIClient:
    pass

class TestToolCallModel(unittest.TestCase):
    def setUp(self):
        # Instantiate providers with mock clients for pure message conversion testing
        self.anthropic = object.__new__(AnthropicProvider)
        self.openai = object.__new__(OpenAIProvider)

    def test_single_tool_call_canonical_conversion_anthropic(self):
        """Single canonical tool call must convert to Claude tool_use with exact name and input."""
        messages = [
            {"role": "user", "content": "Search for user auth"},
            {
                "role": "assistant",
                "content": "Searching...",
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "name": "search_code",
                        "arguments": {"query": "auth_manager", "extension": ".py"}
                    }
                ]
            }
        ]
        claude_msgs, system = self.anthropic._convert_messages(messages)
        self.assertEqual(len(claude_msgs), 2)
        assistant_msg = claude_msgs[1]
        self.assertEqual(assistant_msg["role"], "assistant")
        self.assertEqual(len(assistant_msg["content"]), 2) # text block + tool_use block
        
        tool_block = [b for b in assistant_msg["content"] if b.get("type") == "tool_use"][0]
        self.assertEqual(tool_block["id"], "call_abc123")
        self.assertEqual(tool_block["name"], "search_code")
        self.assertEqual(tool_block["input"], {"query": "auth_manager", "extension": ".py"})

    def test_regression_anthropic_receives_correct_name_and_args(self):
        """
        REGRESSION TEST:
        Proves that Anthropic receives the correct tool name and arguments after a generic
        Sakura tool call, avoiding the bug where 'name' and 'arguments' became None or {}.
        """
        generic_sakura_tool_call = {
            "id": "toolu_01A2B3C4",
            "name": "find_symbol",
            "arguments": {"symbol_name": "AuthManager"}
        }
        messages = [
            {"role": "user", "content": "Where is AuthManager?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [generic_sakura_tool_call]
            }
        ]
        claude_msgs, _ = self.anthropic._convert_messages(messages)
        assistant_turn = claude_msgs[1]
        tool_blocks = [b for b in assistant_turn["content"] if b["type"] == "tool_use"]
        self.assertEqual(len(tool_blocks), 1)
        self.assertEqual(tool_blocks[0]["name"], "find_symbol")
        self.assertEqual(tool_blocks[0]["input"], {"symbol_name": "AuthManager"})
        self.assertIsNotNone(tool_blocks[0]["name"])
        self.assertNotEqual(tool_blocks[0]["input"], {})

    def test_parallel_tool_calls_anthropic(self):
        """Multiple parallel tool calls in one turn must convert into multiple tool_use blocks."""
        messages = [
            {
                "role": "assistant",
                "content": "Running checks...",
                "tool_calls": [
                    {"id": "call_1", "name": "run_linter", "arguments": {"command": "npm run lint"}},
                    {"id": "call_2", "name": "run_typecheck", "arguments": {"command": "tsc"}}
                ]
            }
        ]
        claude_msgs, _ = self.anthropic._convert_messages(messages)
        content_blocks = claude_msgs[0]["content"]
        tool_use_blocks = [b for b in content_blocks if b["type"] == "tool_use"]
        self.assertEqual(len(tool_use_blocks), 2)
        self.assertEqual(tool_use_blocks[0]["name"], "run_linter")
        self.assertEqual(tool_use_blocks[1]["name"], "run_typecheck")

    def test_consecutive_tool_results_batching_anthropic(self):
        """Consecutive tool results must be batched into a single user turn for Claude."""
        messages = [
            {"role": "user", "content": "Run checks"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "t1", "arguments": {}},
                    {"id": "c2", "name": "t2", "arguments": {}}
                ]
            },
            {"role": "tool", "tool_call_id": "c1", "content": "Result 1"},
            {"role": "tool", "tool_call_id": "c2", "content": "Result 2"}
        ]
        claude_msgs, _ = self.anthropic._convert_messages(messages)
        # Expected: user (prompt), assistant (tool_uses), user (batch of 2 tool_results)
        self.assertEqual(len(claude_msgs), 3)
        self.assertEqual(claude_msgs[2]["role"], "user")
        self.assertIsInstance(claude_msgs[2]["content"], list)
        self.assertEqual(len(claude_msgs[2]["content"]), 2)
        self.assertEqual(claude_msgs[2]["content"][0]["type"], "tool_result")
        self.assertEqual(claude_msgs[2]["content"][0]["tool_use_id"], "c1")
        self.assertEqual(claude_msgs[2]["content"][1]["type"], "tool_result")
        self.assertEqual(claude_msgs[2]["content"][1]["tool_use_id"], "c2")

    def test_openai_conversion_from_canonical(self):
        """OpenAI adapter converts canonical tool calls to function schema with json-serialized arguments."""
        messages = [
            {"role": "user", "content": "Check repository"},
            {
                "role": "assistant",
                "content": "Inspecting",
                "tool_calls": [
                    {"id": "call_1", "name": "repository_tree", "arguments": {"max_depth": 2}}
                ]
            },
            {"role": "tool", "tool_call_id": "call_1", "content": '{"tree": ["/src"]}'}
        ]
        converted = self.openai._convert_messages_for_openai(messages)
        self.assertEqual(len(converted), 3)
        asst = converted[1]
        self.assertEqual(asst["role"], "assistant")
        self.assertEqual(asst["tool_calls"][0]["type"], "function")
        self.assertEqual(asst["tool_calls"][0]["function"]["name"], "repository_tree")
        self.assertEqual(json.loads(asst["tool_calls"][0]["function"]["arguments"]), {"max_depth": 2})
        self.assertEqual(converted[2]["role"], "tool")
        self.assertEqual(converted[2]["tool_call_id"], "call_1")

    def test_missing_or_invalid_arguments_resilience(self):
        """Invalid JSON string or missing arguments do not raise exceptions."""
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call_bad", "name": "broken_args", "arguments": "{invalid_json"}
                ]
            }
        ]
        claude_msgs, _ = self.anthropic._convert_messages(messages)
        tool_block = claude_msgs[0]["content"][0]
        self.assertEqual(tool_block["name"], "broken_args")
        self.assertEqual(tool_block["input"], {})

    def test_multi_turn_tool_loop_trajectory(self):
        """Full multi-turn tool interaction preserves integrity across turns."""
        trajectory = [
            {"role": "user", "content": "Please inspect calc.py"},
            {
                "role": "assistant",
                "content": "Reading file",
                "tool_calls": [{"id": "call_read", "name": "read_file", "arguments": {"path": "calc.py"}}]
            },
            {"role": "tool", "tool_call_id": "call_read", "content": "def add(a, b): return a + b"},
            {
                "role": "assistant",
                "content": "The file contains the add function."
            }
        ]
        claude_msgs, _ = self.anthropic._convert_messages(trajectory)
        self.assertEqual(len(claude_msgs), 4)
        openai_msgs = self.openai._convert_messages_for_openai(trajectory)
        self.assertEqual(len(openai_msgs), 4)

if __name__ == "__main__":
    unittest.main()

"""
Sakura AI — Guarded Deterministic Test Providers (Test-Only)

Strictly gated behind BOTH ENVIRONMENT=test AND SAKURA_DETERMINISTIC_TEST_PROVIDERS=1.
Never activates in production, staging, or development. Allows full-stack browser-to-backend
integration tests to exercise real HTTP routes, DB persistence, queues, workers, SSE streaming,
and storage without uncontrolled external LLM or image-provider API calls.
"""

import os
import struct
import zlib
import json
from typing import AsyncGenerator, List, Dict, Any, Optional
from llm.providers.base import LLMProvider


def is_deterministic_test_provider_enabled() -> bool:
    """
    Returns True ONLY when running in explicit test environment with
    SAKURA_DETERMINISTIC_TEST_PROVIDERS=1. Always False in production/staging/dev.
    """
    env = os.getenv("ENVIRONMENT", "").strip().lower()
    flag = os.getenv("SAKURA_DETERMINISTIC_TEST_PROVIDERS", "0").strip().lower()
    return env == "test" and flag in ("1", "true", "yes")


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def build_deterministic_test_png(prompt: str, width: int = 64, height: int = 64) -> bytes:
    """
    Produces a valid, browser-renderable PNG binary (>= 9 KB) using only stdlib zlib/struct
    so real storage, downloads, and QualityEvaluator validation execute end-to-end.
    """
    w = max(32, min(int(width), 128))
    h = max(32, min(int(height), 128))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)  # 8-bit RGB

    # Generate a simple sakura-pink gradient image (uncompressed zlib level=0 keeps PNG valid & >8KB)
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # PNG filter type None
        for x in range(w):
            r = min(255, 220 + ((x + y) % 35))
            g = min(255, 110 + ((y * 2) % 90))
            b = min(255, 160 + ((x * 2) % 75))
            rows.extend((r, g, b))

    compressed = zlib.compress(bytes(rows), level=0)
    meta_text = f"sakura_test_prompt\x00{(prompt or '')[:200]}".encode("utf-8", errors="ignore")

    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"tEXt", meta_text)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


class DeterministicTestProvider(LLMProvider):
    """Deterministic LLM adapter for real full-stack integration testing (ENVIRONMENT=test only)."""

    model = "sakura-deterministic-test-v1"

    def _extract_last_user_text(self, messages: List[Dict[str, Any]]) -> str:
        for msg in reversed(messages or []):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content.strip()
        return ""

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs,
    ) -> str:
        clean = (prompt or "").strip()
        return f"Sakura integration response: {clean}"

    async def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        text = await self.generate(prompt, system_prompt, history, temperature, max_tokens, **kwargs)
        for idx, word in enumerate(text.split(" ")):
            yield word if idx == 0 else f" {word}"

    async def stream_messages(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        last_user = self._extract_last_user_text(messages)
        text = f"Sakura integration response: {last_user}"
        for idx, word in enumerate(text.split(" ")):
            yield word if idx == 0 else f" {word}"

    async def generate_structured(
        self,
        prompt: str,
        response_model: Any,
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> Any:
        payload = {"summary": f"Deterministic structured output for: {(prompt or '')[:80]}"}
        if hasattr(response_model, "model_validate"):
            return response_model.model_validate(payload)
        return json.dumps(payload)

    async def tool_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1500,
        **kwargs,
    ) -> Dict[str, Any]:
        tool_names = {
            (t.get("function") or {}).get("name")
            for t in (tools or [])
            if isinstance(t, dict)
        }
        # CodingAgent tool set: execute full canonical engineering loop:
        # EXPLORE -> IMPLEMENT (buggy + test) -> TEST (fail) -> FIX (patch) -> RETEST (pass) -> REVIEW DIFF -> DELIVER
        if "write_file" in tool_names and "repository_tree" in tool_names:
            tool_msgs = [m for m in (messages or []) if m.get("role") == "tool"]
            step = len(tool_msgs)
            if step == 0:
                return {
                    "content": "Exploring repository and implementing initial module and test suite.",
                    "tool_calls": [
                        {
                            "id": "call_det_tree_0",
                            "name": "repository_tree",
                            "arguments": {"max_depth": 2},
                        },
                        {
                            "id": "call_det_write_1",
                            "name": "write_file",
                            "arguments": {
                                "path": "sakura_fullstack_check.py",
                                "content": "def add(a, b):\n    return a - b  # intentional bug\n",
                            },
                        },
                        {
                            "id": "call_det_write_2",
                            "name": "write_file",
                            "arguments": {
                                "path": "test_sakura_fullstack.py",
                                "content": (
                                    "import os\n"
                                    "from sakura_fullstack_check import add\n"
                                    "assert not os.path.exists('/workspaces'), 'parent /workspaces leaked!'\n"
                                    "assert not os.environ.get('HOST_SENSITIVE_SECRET'), 'host secret leaked!'\n"
                                    "assert add(2, 3) == 5, f'Expected 5, got {add(2, 3)}'\n"
                                    "print('SAKURA_REMOTE_DOCKER_TESTS_PASSED')\n"
                                ),
                            },
                        },
                    ],
                    "finish_reason": "tool_calls",
                }
            if step == 3 and "run_tests" in tool_names:
                return {
                    "content": "Running initial test suite inside isolated sandbox.",
                    "tool_calls": [
                        {
                            "id": "call_det_test_fail",
                            "name": "run_tests",
                            "arguments": {
                                "command": "python3 test_sakura_fullstack.py",
                            },
                        }
                    ],
                    "finish_reason": "tool_calls",
                }
            if step == 4 and "apply_patch" in tool_names:
                return {
                    "content": "Inspecting failing test output and patching add() in sakura_fullstack_check.py.",
                    "tool_calls": [
                        {
                            "id": "call_det_patch",
                            "name": "apply_patch",
                            "arguments": {
                                "path": "sakura_fullstack_check.py",
                                "target_content": "return a - b  # intentional bug",
                                "replacement_content": "return a + b",
                            },
                        }
                    ],
                    "finish_reason": "tool_calls",
                }
            if step == 5 and "run_tests" in tool_names:
                return {
                    "content": "Re-running verification tests after fix.",
                    "tool_calls": [
                        {
                            "id": "call_det_test_pass",
                            "name": "run_tests",
                            "arguments": {
                                "command": "python3 test_sakura_fullstack.py",
                            },
                        }
                    ],
                    "finish_reason": "tool_calls",
                }
            if step == 6 and "git_diff" in tool_names:
                return {
                    "content": "Reviewing git diff prior to delivery.",
                    "tool_calls": [
                        {
                            "id": "call_det_diff",
                            "name": "git_diff",
                            "arguments": {},
                        }
                    ],
                    "finish_reason": "tool_calls",
                }
            return {
                "content": "Fixed add() in sakura_fullstack_check.py and verified tests pass inside the isolated Docker sandbox.",
                "tool_calls": [],
                "finish_reason": "stop",
            }

        # Standard chat Agent: stop tool loop immediately and stream deterministic reply
        return {
            "content": None,
            "tool_calls": [],
            "finish_reason": "stop",
        }

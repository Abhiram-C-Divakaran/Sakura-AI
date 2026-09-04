import json
import uuid
import time
from typing import Dict, Any, List, Optional, AsyncGenerator
from sqlalchemy.orm import Session
from database.models import CodingTask, ToolExecution, RepositoryWorkspace, User
from coding.tools import CodingToolchain
from llm.router import LLMRouter

CODING_AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "repository_tree",
            "description": "Inspect directory tree of the repository workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Subdirectory to inspect (optional)"},
                    "max_depth": {"type": "integer", "description": "Maximum depth level (default 3)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents with optional line numbers (1-indexed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "start_line": {"type": "integer", "description": "First line to read (optional)"},
                    "end_line": {"type": "integer", "description": "Last line to read (optional)"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for symbols, text or regex patterns across workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Pattern or string to search"},
                    "is_regex": {"type": "boolean", "description": "Whether query is a regex"},
                    "extension": {"type": "string", "description": "Optional file extension filter (e.g. '.py', '.ts')"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": "Locate definition of a function, class or interface across the codebase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {"type": "string", "description": "Name of function or class"}
                },
                "required": ["symbol_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with exact content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "content": {"type": "string", "description": "Full file content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Targeted patch replacing an exact unique snippet in a file with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "target_content": {"type": "string", "description": "Exact text chunk to replace"},
                    "replacement_content": {"type": "string", "description": "Replacement text chunk"}
                },
                "required": ["path", "target_content", "replacement_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a safe shell command inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command line to execute"},
                    "cwd": {"type": "string", "description": "Working directory relative to workspace root (optional)"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the project test suite or targeted test file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Test command (e.g. 'pytest tests/test_auth.py', 'npm test')"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Inspect git diff of all modifications made so far.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Specific file path (optional)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Check current git status of modified or untracked files.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

class CodingAgent:
    """
    Elite repository-level software engineering agent implementing the
    canonical Sakura Frontier Coding Engine loop.
    """

    def __init__(
        self,
        db: Session,
        workspace: RepositoryWorkspace,
        user: User,
        llm_router: LLMRouter,
        intensity: str = "high"
    ):
        self.db = db
        self.workspace = workspace
        self.user = user
        self.llm_router = llm_router
        self.intensity = intensity.lower()
        self.toolchain = CodingToolchain(workspace.workspace_path)
        self.modified_files: List[str] = []
        self.tests_run: List[Dict[str, Any]] = []

    async def execute_tool(self, task_id: Optional[uuid.UUID], tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches tool call to toolchain and logs execution record."""
        start_time = time.time()
        res = {"success": False, "tool": tool_name, "error": "Unknown tool"}

        if tool_name == "repository_tree":
            res = await self.toolchain.repository_tree(args.get("path"), args.get("max_depth", 3))
        elif tool_name == "read_file":
            res = await self.toolchain.read_file(args.get("path", ""), args.get("start_line"), args.get("end_line"))
        elif tool_name == "search_code":
            res = await self.toolchain.search_code(args.get("query", ""), args.get("is_regex", False), args.get("extension"))
        elif tool_name == "find_symbol":
            res = await self.toolchain.find_symbol(args.get("symbol_name", ""))
        elif tool_name == "write_file":
            path = args.get("path", "")
            res = await self.toolchain.write_file(path, args.get("content", ""))
            if res.get("success") and path not in self.modified_files:
                self.modified_files.append(path)
        elif tool_name == "apply_patch":
            path = args.get("path", "")
            res = await self.toolchain.apply_patch(path, args.get("target_content", ""), args.get("replacement_content", ""))
            if res.get("success") and path not in self.modified_files:
                self.modified_files.append(path)
        elif tool_name == "run_command":
            res = await self.toolchain.run_command(args.get("command", ""), args.get("cwd"))
        elif tool_name == "run_tests":
            res = await self.toolchain.run_tests(args.get("command", "npm test"))
            self.tests_run.append(res)
        elif tool_name == "git_diff":
            res = await self.toolchain.git_diff(args.get("file_path"))
        elif tool_name == "git_status":
            res = await self.toolchain.git_status()

        duration_ms = int((time.time() - start_time) * 1000)

        # Record tool execution if attached to task
        if task_id:
            try:
                exec_record = ToolExecution(
                    coding_task_id=task_id,
                    tool_name=tool_name,
                    arguments=args,
                    status="SUCCESS" if res.get("success") else "FAILED",
                    stdout_preview=str(res.get("stdout") or res.get("content") or res.get("tree") or "")[:2000],
                    stderr_preview=str(res.get("stderr") or res.get("error") or "")[:2000],
                    exit_code=res.get("exit_code"),
                    duration_ms=duration_ms
                )
                self.db.add(exec_record)
                self.db.commit()
            except Exception:
                pass

        return res

    async def run_task_stream(self, task: CodingTask) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Executes an end-to-end coding task with tool streaming, test verification,
        diff review, and completion summary.
        """
        task.status = "EXPLORING"
        self.db.commit()

        system_prompt = f"""You are SAKURA AI, an elite frontier software engineering assistant working on a real repository.
Workspace: '{self.workspace.name}' ({self.workspace.active_branch})

ABSOLUTE CODING PRINCIPLES:
1. REPOSITORY-FIRST: Do not guess file paths or contents. Use repository_tree, read_file, search_code, find_symbol.
2. MINIMAL NECESSARY CHANGE: Prefer the smallest coherent change that correctly solves the problem.
3. TEST-FIRST VERIFICATION: After editing code, you MUST run relevant tests to verify the solution.
4. NO FAKE CLAIMS: Never claim code works or tests pass unless run_tests or run_command returned exit_code 0.
5. DIFF REVIEW: Before finishing, run git_diff to ensure your changes are clean.

Deliver a concise engineering summary at the end:
- Implemented: summary of changes
- Verified: tests run and results
- Files changed: list of modified files
- Notes: operational caveats or follow-ups
"""

        user_prompt = f"""OBJECTIVE:
{task.objective}

Please execute this task: inspect the codebase, implement the changes, run tests to verify, review the diff, and summarize your work."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # Select model based on intensity
        intent = "repository_coding" if self.intensity == "high" else "code_generation"
        provider_name, provider = self.llm_router.get_provider(intent)

        max_turns = 15 if self.intensity == "high" else (8 if self.intensity == "medium" else 4)

        for turn in range(max_turns):
            yield {"phase": task.status, "turn": turn + 1, "message": f"Agent iteration {turn + 1}..."}

            # Call provider-neutral tool turn
            try:
                turn_result = await provider.tool_turn(
                    messages=messages,
                    tools=CODING_AGENT_TOOLS,
                    temperature=0.2,
                    max_tokens=2000
                )
            except Exception as e:
                yield {"error": f"LLM provider error: {str(e)}"}
                task.status = "FAILED"
                self.db.commit()
                return

            tool_calls = turn_result.get("tool_calls", [])
            content = turn_result.get("content")

            if tool_calls:
                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": tool_calls
                })

                for tc in tool_calls:
                    fn_name = tc.get("name")
                    fn_args = tc.get("arguments", {})
                    if isinstance(fn_args, str):
                        try:
                            fn_args = json.loads(fn_args)
                        except Exception:
                            fn_args = {}

                    yield {
                        "phase": "TOOL_EXECUTION",
                        "tool": fn_name,
                        "args": fn_args
                    }

                    tool_res = await self.execute_tool(task.id, fn_name, fn_args)

                    # Update phase based on tool
                    if fn_name in ["write_file", "apply_patch"]:
                        task.status = "IMPLEMENTING"
                    elif fn_name in ["run_tests", "run_command"]:
                        task.status = "TESTING"
                    self.db.commit()

                    yield {
                        "phase": "TOOL_RESULT",
                        "tool": fn_name,
                        "success": tool_res.get("success", False),
                        "snippet": str(tool_res.get("stdout") or tool_res.get("content") or tool_res.get("error") or "")[:200]
                    }

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", str(uuid.uuid4())),
                        "content": json.dumps(tool_res)
                    })
                continue
            else:
                # Agent concluded and provided final response
                final_text = content or "Task complete."
                
                # Verify diff before completing
                diff_res = await self.toolchain.git_diff()
                task.files_modified = self.modified_files
                task.verification_summary = {
                    "tests_run_count": len(self.tests_run),
                    "all_passed": all(t.get("exit_code") == 0 for t in self.tests_run) if self.tests_run else False,
                    "diff_bytes": len(diff_res.get("stdout", ""))
                }
                task.status = "COMPLETED"
                self.db.commit()

                yield {
                    "phase": "COMPLETED",
                    "files_modified": self.modified_files,
                    "verification": task.verification_summary,
                    "final_output": final_text
                }
                return

        # Max iterations reached
        task.status = "COMPLETED"
        task.files_modified = self.modified_files
        self.db.commit()
        yield {"phase": "COMPLETED", "message": "Max tool turns reached. Changes applied to workspace."}

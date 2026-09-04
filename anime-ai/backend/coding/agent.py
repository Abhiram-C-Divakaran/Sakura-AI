import json
import uuid
import time
from typing import Dict, Any, List, Optional, AsyncGenerator
from sqlalchemy.orm import Session
from database.models import CodingTask, ToolExecution, RepositoryWorkspace, User, TaskOutcome
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
    },
    {
        "type": "function",
        "function": {
            "name": "read_files",
            "description": "Read multiple files sequentially.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of relative file paths"
                    }
                },
                "required": ["paths"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_file",
            "description": "Locate file paths matching a filename pattern or glob.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Filename pattern to match (e.g. '*auth*', 'agent.py')"}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Creates a new file in the workspace without overwriting existing files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "content": {"type": "string", "description": "Initial file content"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Deletes a file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "rename_file",
            "description": "Renames or moves a file within the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "Current relative file path"},
                    "new_path": {"type": "string", "description": "New relative file path"}
                },
                "required": ["old_path", "new_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_linter",
            "description": "Runs code linter (e.g. ruff, eslint, flake8) inside workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Linter command line"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_formatter",
            "description": "Runs code formatter (e.g. prettier, black) inside workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Formatter command line"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_typecheck",
            "description": "Runs static typechecker (e.g. mypy, tsc) inside workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Typecheck command line"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_build",
            "description": "Runs build command (e.g. npm run build, cargo build, make) inside workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Build command line"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Inspect recent git commits in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_count": {"type": "integer", "description": "Maximum number of commits (default 10)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_show",
            "description": "Inspect git commit or tag details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "commit": {"type": "string", "description": "Commit SHA, branch, or tag (default HEAD)"}
                }
            }
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
        elif tool_name == "read_files":
            res = await self.toolchain.read_files(args.get("paths", []))
        elif tool_name == "search_code":
            res = await self.toolchain.search_code(args.get("query", ""), args.get("is_regex", False), args.get("extension"))
        elif tool_name == "find_file":
            res = await self.toolchain.find_file(args.get("pattern", ""))
        elif tool_name == "find_symbol":
            res = await self.toolchain.find_symbol(args.get("symbol_name", ""))
        elif tool_name == "write_file":
            path = args.get("path", "")
            res = await self.toolchain.write_file(path, args.get("content", ""))
            if res.get("success") and path not in self.modified_files:
                self.modified_files.append(path)
        elif tool_name == "create_file":
            path = args.get("path", "")
            res = await self.toolchain.create_file(path, args.get("content", ""))
            if res.get("success") and path not in self.modified_files:
                self.modified_files.append(path)
        elif tool_name == "apply_patch":
            path = args.get("path", "")
            res = await self.toolchain.apply_patch(path, args.get("target_content", ""), args.get("replacement_content", ""))
            if res.get("success") and path not in self.modified_files:
                self.modified_files.append(path)
        elif tool_name == "delete_file":
            path = args.get("path", "")
            res = await self.toolchain.delete_file(path)
            if res.get("success") and path not in self.modified_files:
                self.modified_files.append(path)
        elif tool_name == "rename_file":
            old_path = args.get("old_path", "")
            new_path = args.get("new_path", "")
            res = await self.toolchain.rename_file(old_path, new_path)
            if res.get("success"):
                if old_path not in self.modified_files:
                    self.modified_files.append(old_path)
                if new_path not in self.modified_files:
                    self.modified_files.append(new_path)
        elif tool_name == "run_command":
            res = await self.toolchain.run_command(args.get("command", ""), args.get("cwd"))
        elif tool_name == "run_tests":
            res = await self.toolchain.run_tests(args.get("command", "npm test"))
            self.tests_run.append(res)
        elif tool_name == "run_linter":
            res = await self.toolchain.run_linter(args.get("command", "npm run lint"))
        elif tool_name == "run_formatter":
            res = await self.toolchain.run_formatter(args.get("command", "npm run format"))
        elif tool_name == "run_typecheck":
            res = await self.toolchain.run_typecheck(args.get("command", "npm run typecheck"))
        elif tool_name == "run_build":
            res = await self.toolchain.run_build(args.get("command", "npm run build"))
        elif tool_name == "git_diff":
            res = await self.toolchain.git_diff(args.get("file_path"))
        elif tool_name == "git_status":
            res = await self.toolchain.git_status()
        elif tool_name == "git_log":
            res = await self.toolchain.git_log(args.get("max_count", 10))
        elif tool_name == "git_show":
            res = await self.toolchain.git_show(args.get("commit", "HEAD"))

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
        task.status = TaskOutcome.EXPLORING
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
                task.status = TaskOutcome.FAILED
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
                    if fn_name in ["write_file", "create_file", "apply_patch", "delete_file", "rename_file"]:
                        task.status = TaskOutcome.IMPLEMENTING
                    elif fn_name in ["run_tests", "run_command", "run_linter", "run_typecheck", "run_build"]:
                        task.status = TaskOutcome.TESTING
                    elif fn_name in ["git_diff", "git_status", "git_log", "git_show"]:
                        task.status = TaskOutcome.REVIEWING
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
                tests_passed = len(self.tests_run) > 0 and all(t.get("exit_code") == 0 for t in self.tests_run)
                tests_failed = len(self.tests_run) > 0 and any(t.get("exit_code") != 0 for t in self.tests_run)

                task.files_modified = self.modified_files
                task.verification_summary = {
                    "tests_run_count": len(self.tests_run),
                    "all_passed": tests_passed,
                    "diff_bytes": len(diff_res.get("stdout", ""))
                }

                if tests_failed:
                    task.status = TaskOutcome.FAILED
                elif tests_passed:
                    task.status = TaskOutcome.COMPLETED_VERIFIED
                elif self.modified_files:
                    task.status = TaskOutcome.COMPLETED_UNVERIFIED
                else:
                    task.status = TaskOutcome.COMPLETED_VERIFIED

                self.db.commit()

                yield {
                    "phase": task.status,
                    "files_modified": self.modified_files,
                    "verification": task.verification_summary,
                    "final_output": final_text
                }
                return

        # Max iterations reached
        task.status = TaskOutcome.MAX_ITERATIONS
        task.files_modified = self.modified_files
        self.db.commit()
        yield {
            "phase": TaskOutcome.MAX_ITERATIONS,
            "message": "Max tool turns reached without final conclusion."
        }

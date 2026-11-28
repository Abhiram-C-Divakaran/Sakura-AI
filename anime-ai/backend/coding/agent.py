import json
import uuid
import time
from typing import Dict, Any, List, Optional, AsyncGenerator, Callable
from sqlalchemy.orm import Session
from database.db import get_db_context
from database.models import CodingTask, ToolExecution, RepositoryWorkspace, User, TaskOutcome, utc_now
from coding.tools import CodingToolchain
from coding.security import redact_sensitive_data, redact_sensitive_text
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
        db: Optional[Session],
        workspace: RepositoryWorkspace,
        user: User,
        llm_router: LLMRouter,
        intensity: str = "high"
    ):
        self.db = db
        self.workspace = workspace
        self.user = user
        self.llm_router = llm_router
        self.intensity = (intensity or "high").lower()
        self.toolchain = CodingToolchain(
            workspace.workspace_path,
            workspace_id=str(workspace.id),
            db=db,
            user_id=user.id
        )
        self.modified_files: List[str] = []
        self._mutation_epoch: int = 0
        self.tests_run: List[Dict[str, Any]] = []
        self.linters_run: List[Dict[str, Any]] = []
        self.typechecks_run: List[Dict[str, Any]] = []
        self.builds_run: List[Dict[str, Any]] = []
        self.diff_reviewed: bool = False

    def _evaluate_latest_verification_runs(self, runs: List[Dict[str, Any]]) -> tuple[int, bool, bool]:
        """
        Evaluates verification command runs executed at the current mutation epoch
        (i.e. after the latest file modification). Keeps the latest outcome per
        distinct command so reproducing a failing test, patching code, and re-running
        the passing test resolves truthfully to passed.
        Returns: (effective_run_count, all_passed, any_failed)
        """
        current_epoch_runs = [
            r for r in runs if r.get("mutation_epoch", self._mutation_epoch) == self._mutation_epoch
        ]
        if not current_epoch_runs:
            return 0, False, False

        latest_by_cmd: Dict[str, Dict[str, Any]] = {}
        for idx, run in enumerate(current_epoch_runs):
            cmd_key = str(run.get("command") or f"__run_{idx}").strip()
            latest_by_cmd[cmd_key] = run

        final_runs = list(latest_by_cmd.values())
        all_passed = all(r.get("exit_code") == 0 for r in final_runs)
        any_failed = any(r.get("exit_code") != 0 for r in final_runs)
        return len(final_runs), all_passed, any_failed

    def _persist_task_state(
        self,
        task: CodingTask,
        *,
        status: Optional[str] = None,
        files_modified: Optional[List[str]] = None,
        verification_summary: Optional[Dict[str, Any]] = None,
        completed_at=None,
        persist_to_db: bool = True
    ) -> None:
        """Safely persists CodingTask mutations via a fresh DB context so detached sessions never drop writes."""
        if status is not None:
            task.status = status
        if files_modified is not None:
            task.files_modified = list(files_modified)
        if verification_summary is not None:
            task.verification_summary = dict(verification_summary)
        if completed_at is not None:
            task.completed_at = completed_at

        if not persist_to_db or not getattr(task, "id", None):
            return

        with get_db_context() as db_ctx:
            db_task = db_ctx.query(CodingTask).filter(CodingTask.id == task.id).first()
            if db_task:
                if status is not None:
                    db_task.status = status
                if files_modified is not None:
                    db_task.files_modified = list(files_modified)
                if verification_summary is not None:
                    db_task.verification_summary = dict(verification_summary)
                if completed_at is not None:
                    db_task.completed_at = completed_at
                db_task.updated_at = utc_now()
                db_ctx.commit()

    @staticmethod
    def classify_task_kind(objective: str) -> str:
        """Classifies task objective as READ_ONLY or MUTATING."""
        obj_lower = (objective or "").lower()
        read_only_indicators = [
            "explain", "how does", "what is", "where is", "find where",
            "search for", "review only", "read-only", "inspect only",
            "describe", "understand", "summarize", "analyze architecture"
        ]
        mutating_indicators = [
            "fix", "bug", "patch", "implement", "update", "modify", "change",
            "refactor", "add", "remove", "delete", "create", "write", "rewrite",
            "optimize", "upgrade", "migrate", "convert", "build", "wire", "test and fix"
        ]
        if any(ind in obj_lower for ind in mutating_indicators):
            return "MUTATING"
        if any(ind in obj_lower for ind in read_only_indicators):
            return "READ_ONLY"
        return "MUTATING"

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
            if res.get("success"):
                self._mutation_epoch += 1
                if path not in self.modified_files:
                    self.modified_files.append(path)
        elif tool_name == "create_file":
            path = args.get("path", "")
            res = await self.toolchain.create_file(path, args.get("content", ""))
            if res.get("success"):
                self._mutation_epoch += 1
                if path not in self.modified_files:
                    self.modified_files.append(path)
        elif tool_name == "apply_patch":
            path = args.get("path", "")
            res = await self.toolchain.apply_patch(path, args.get("target_content", ""), args.get("replacement_content", ""))
            if res.get("success"):
                self._mutation_epoch += 1
                if path not in self.modified_files:
                    self.modified_files.append(path)
        elif tool_name == "delete_file":
            path = args.get("path", "")
            res = await self.toolchain.delete_file(path)
            if res.get("success"):
                self._mutation_epoch += 1
                if path not in self.modified_files:
                    self.modified_files.append(path)
        elif tool_name == "rename_file":
            old_path = args.get("old_path", "")
            new_path = args.get("new_path", "")
            res = await self.toolchain.rename_file(old_path, new_path)
            if res.get("success"):
                self._mutation_epoch += 1
                if old_path not in self.modified_files:
                    self.modified_files.append(old_path)
                if new_path not in self.modified_files:
                    self.modified_files.append(new_path)
        elif tool_name == "run_command":
            res = await self.toolchain.run_command(
                command=args.get("command", ""),
                cwd=args.get("cwd"),
                allow_network=args.get("allow_network", False),
                network_authorization_id=args.get("network_authorization_id"),
                network_capability=args.get("network_capability")
            )
        elif tool_name == "run_tests":
            cmd = args.get("command", "npm test")
            res = await self.toolchain.run_tests(cmd)
            self.tests_run.append({**res, "command": cmd, "mutation_epoch": self._mutation_epoch})
        elif tool_name == "run_linter":
            cmd = args.get("command", "npm run lint")
            res = await self.toolchain.run_linter(cmd)
            self.linters_run.append({**res, "command": cmd, "mutation_epoch": self._mutation_epoch})
        elif tool_name == "run_formatter":
            res = await self.toolchain.run_formatter(args.get("command", "npm run format"))
        elif tool_name == "run_typecheck":
            cmd = args.get("command", "npm run typecheck")
            res = await self.toolchain.run_typecheck(cmd)
            self.typechecks_run.append({**res, "command": cmd, "mutation_epoch": self._mutation_epoch})
        elif tool_name == "run_build":
            cmd = args.get("command", "npm run build")
            res = await self.toolchain.run_build(cmd)
            self.builds_run.append({**res, "command": cmd, "mutation_epoch": self._mutation_epoch})
        elif tool_name == "git_diff":
            res = await self.toolchain.git_diff(args.get("file_path"))
            self.diff_reviewed = True
        elif tool_name == "git_status":
            res = await self.toolchain.git_status()
        elif tool_name == "git_log":
            res = await self.toolchain.git_log(args.get("max_count", 10))
        elif tool_name == "git_show":
            res = await self.toolchain.git_show(args.get("commit", "HEAD"))

        duration_ms = int((time.time() - start_time) * 1000)

        # Record tool execution if attached to task (redacting secrets and using fresh session)
        if task_id:
            try:
                safe_args = redact_sensitive_data(args)
                safe_stdout = redact_sensitive_text(str(res.get("stdout") or res.get("content") or res.get("tree") or ""))[:2000]
                safe_stderr = redact_sensitive_text(str(res.get("stderr") or res.get("error") or ""))[:2000]
                with get_db_context() as db_ctx:
                    exec_record = ToolExecution(
                        coding_task_id=task_id,
                        tool_name=tool_name,
                        arguments=safe_args,
                        status="SUCCESS" if res.get("success") else "FAILED",
                        stdout_preview=safe_stdout,
                        stderr_preview=safe_stderr,
                        exit_code=res.get("exit_code"),
                        duration_ms=duration_ms
                    )
                    db_ctx.add(exec_record)
                    db_ctx.commit()
            except Exception:
                pass

        return res

    async def run_task_stream(
        self,
        task: CodingTask,
        should_stop: Optional[Callable[[], bool]] = None,
        persist_directly: bool = True
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Executes an end-to-end coding task with tool streaming, test verification,
        diff review, and completion summary.
        Checks should_stop() before every LLM turn and tool execution to guarantee
        cooperative cancellation / lease-loss termination.
        """
        if should_stop and should_stop():
            return

        self._persist_task_state(task, status=TaskOutcome.EXPLORING, persist_to_db=persist_directly)

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
            if should_stop and should_stop():
                return

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
                self._persist_task_state(
                    task,
                    status=TaskOutcome.FAILED,
                    files_modified=self.modified_files,
                    completed_at=utc_now(),
                    persist_to_db=persist_directly
                )
                return

            if should_stop and should_stop():
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
                    if should_stop and should_stop():
                        return

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
                        "args": redact_sensitive_data(fn_args)
                    }

                    tool_res = await self.execute_tool(task.id, fn_name, fn_args)

                    if should_stop and should_stop():
                        return

                    # Update phase based on tool
                    next_status = task.status
                    if fn_name in ["write_file", "create_file", "apply_patch", "delete_file", "rename_file"]:
                        next_status = TaskOutcome.IMPLEMENTING
                    elif fn_name in ["run_tests", "run_command", "run_linter", "run_typecheck", "run_build"]:
                        next_status = TaskOutcome.TESTING
                    elif fn_name in ["git_diff", "git_status", "git_log", "git_show"]:
                        next_status = TaskOutcome.REVIEWING
                    self._persist_task_state(
                        task,
                        status=next_status,
                        files_modified=self.modified_files,
                        persist_to_db=persist_directly
                    )

                    yield {
                        "phase": "TOOL_RESULT",
                        "tool": fn_name,
                        "success": tool_res.get("success", False),
                        "snippet": redact_sensitive_text(str(tool_res.get("stdout") or tool_res.get("content") or tool_res.get("error") or ""))[:200]
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
                self.diff_reviewed = True

                task_kind = self.classify_task_kind(task.objective)
                if self.modified_files:
                    task_kind = "MUTATING"

                tests_run_count, tests_passed, tests_failed = self._evaluate_latest_verification_runs(self.tests_run)

                lint_count, lint_all_passed, lint_failed = self._evaluate_latest_verification_runs(self.linters_run)
                lint_passed = lint_all_passed if lint_count > 0 else None

                tc_count, tc_all_passed, typecheck_failed = self._evaluate_latest_verification_runs(self.typechecks_run)
                typecheck_passed = tc_all_passed if tc_count > 0 else None

                build_count, build_all_passed, build_failed = self._evaluate_latest_verification_runs(self.builds_run)
                build_passed = build_all_passed if build_count > 0 else None

                unverified_reasons = []

                if task_kind == "MUTATING":
                    if not self.modified_files:
                        unverified_reasons.append("No files were modified for a mutating task objective.")
                    if tests_run_count == 0:
                        unverified_reasons.append("No test suite was executed to verify file modifications.")
                    elif tests_failed:
                        unverified_reasons.append("One or more executed test suites failed.")
                    if lint_failed:
                        unverified_reasons.append("Linter reported errors.")
                    if typecheck_failed:
                        unverified_reasons.append("Typecheck command failed.")
                    if build_failed:
                        unverified_reasons.append("Build command failed.")
                    
                    if tests_failed or build_failed:
                        task.status = TaskOutcome.FAILED
                    elif not self.modified_files:
                        task.status = TaskOutcome.FAILED
                    elif tests_passed and not typecheck_failed and not lint_failed:
                        task.status = TaskOutcome.COMPLETED_VERIFIED
                    else:
                        task.status = TaskOutcome.COMPLETED_UNVERIFIED
                else: # READ_ONLY
                    if self.modified_files:
                        unverified_reasons.append("Unexpected file modifications detected during read-only task.")
                        task.status = TaskOutcome.COMPLETED_UNVERIFIED
                    else:
                        task.status = TaskOutcome.COMPLETED_VERIFIED

                verification_passed = (len(unverified_reasons) == 0 and task.status == TaskOutcome.COMPLETED_VERIFIED)

                verification_summary = {
                    "task_kind": task_kind,
                    "files_changed": self.modified_files,
                    "tests": {
                        "run_count": tests_run_count,
                        "all_passed": tests_passed,
                        "has_failures": tests_failed
                    },
                    "lint": {
                        "run": len(self.linters_run) > 0,
                        "passed": lint_passed
                    },
                    "typecheck": {
                        "run": len(self.typechecks_run) > 0,
                        "passed": typecheck_passed
                    },
                    "build": {
                        "run": len(self.builds_run) > 0,
                        "passed": build_passed
                    },
                    "diff_reviewed": self.diff_reviewed,
                    "verification_passed": verification_passed,
                    "unverified_reasons": unverified_reasons
                }

                self._persist_task_state(
                    task,
                    status=task.status,
                    files_modified=self.modified_files,
                    verification_summary=verification_summary,
                    completed_at=utc_now(),
                    persist_to_db=persist_directly
                )

                yield {
                    "phase": task.status,
                    "files_modified": self.modified_files,
                    "verification": task.verification_summary,
                    "final_output": final_text
                }
                return

        # Max iterations reached
        self._persist_task_state(
            task,
            status=TaskOutcome.MAX_ITERATIONS,
            files_modified=self.modified_files,
            completed_at=utc_now(),
            persist_to_db=persist_directly
        )
        yield {
            "phase": TaskOutcome.MAX_ITERATIONS,
            "message": "Max tool turns reached without final conclusion."
        }

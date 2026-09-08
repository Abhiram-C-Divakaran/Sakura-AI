import os
import time
from typing import Dict, Any, List, Optional
from coding.security import WorkspaceSecurity, SecurityException
from coding.executor import SandboxExecutor
from coding.git_manager import GitManager
from coding.code_search import CodeSearchEngine
from coding.patching import FilePatcher

class CodingToolchain:
    """
    Unified, structured coding tools implementation executing directly
    inside an isolated workspace.
    """

    def __init__(self, workspace_root: str):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))
        self.executor = SandboxExecutor(self.workspace_root)
        self.git = GitManager(self.workspace_root)
        self.searcher = CodeSearchEngine(self.workspace_root)
        self.patcher = FilePatcher(self.workspace_root)

    # ─── Navigation & Reading ────────────────────────────────────────────────

    async def repository_tree(self, path: Optional[str] = None, max_depth: int = 3) -> Dict[str, Any]:
        """Returns directory tree structure of workspace."""
        start_time = time.time()
        base_dir = self.workspace_root
        if path:
            try:
                base_dir = WorkspaceSecurity.resolve_safe_path(self.workspace_root, path)
            except SecurityException as e:
                return {"success": False, "tool": "repository_tree", "error": str(e)}

        tree = []
        base_depth = base_dir.count(os.sep)
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".next", "__pycache__", "venv", ".venv", "dist", "build"}]
            current_depth = root.count(os.sep) - base_depth
            if current_depth > max_depth:
                dirs.clear()
                continue
            rel_root = os.path.relpath(root, self.workspace_root).replace("\\", "/")
            for d in dirs:
                tree.append({"type": "dir", "path": f"{rel_root}/{d}".lstrip("./")})
            for f in files:
                tree.append({"type": "file", "path": f"{rel_root}/{f}".lstrip("./")})

        return {
            "success": True,
            "tool": "repository_tree",
            "items_count": len(tree),
            "tree": tree[:300],
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    async def read_file(self, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> Dict[str, Any]:
        """Reads content of a file with optional line boundaries (1-indexed)."""
        start_time = time.time()
        try:
            abs_path = WorkspaceSecurity.resolve_safe_path(self.workspace_root, path)
            if not os.path.exists(abs_path):
                return {"success": False, "tool": "read_file", "path": path, "error": f"File '{path}' not found."}

            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            total_lines = len(lines)
            s = max(1, start_line) if start_line else 1
            e = min(total_lines, end_line) if end_line else total_lines
            content = "".join(lines[s - 1:e])

            return {
                "success": True,
                "tool": "read_file",
                "path": path,
                "total_lines": total_lines,
                "start_line": s,
                "end_line": e,
                "content": content,
                "duration_ms": int((time.time() - start_time) * 1000)
            }
        except Exception as e:
            return {"success": False, "tool": "read_file", "path": path, "error": str(e)}

    async def read_files(self, paths: List[str]) -> Dict[str, Any]:
        """Reads multiple files sequentially."""
        start_time = time.time()
        results = {}
        for p in paths:
            res = await self.read_file(p)
            results[p] = res
        return {
            "success": True,
            "tool": "read_files",
            "files": results,
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    async def search_code(self, query: str, is_regex: bool = False, extension: Optional[str] = None) -> Dict[str, Any]:
        """Searches for pattern occurrences across workspace files."""
        start_time = time.time()
        matches = self.searcher.search_text(query, is_regex=is_regex, file_extension=extension)
        return {
            "success": True,
            "tool": "search_code",
            "query": query,
            "matches_count": len(matches),
            "matches": matches,
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    async def find_file(self, pattern: str) -> Dict[str, Any]:
        """Locates file paths matching filename pattern."""
        start_time = time.time()
        files = self.searcher.find_files(pattern)
        return {
            "success": True,
            "tool": "find_file",
            "pattern": pattern,
            "matches": files,
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    async def find_symbol(self, symbol_name: str) -> Dict[str, Any]:
        """Finds definition of a class or function symbol."""
        start_time = time.time()
        defs = self.searcher.find_symbol_definition(symbol_name)
        return {
            "success": True,
            "tool": "find_symbol",
            "symbol": symbol_name,
            "definitions": defs,
            "duration_ms": int((time.time() - start_time) * 1000)
        }

    # ─── File Manipulation ───────────────────────────────────────────────────

    async def write_file(self, path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
        """Creates or replaces a file with exact content."""
        start_time = time.time()
        res = self.patcher.write_file(path, content, overwrite=overwrite)
        res["tool"] = "write_file"
        res["duration_ms"] = int((time.time() - start_time) * 1000)
        return res

    async def create_file(self, path: str, content: str = "") -> Dict[str, Any]:
        """Creates a new file without overwriting if it already exists."""
        return await self.write_file(path, content, overwrite=False)

    async def apply_patch(self, path: str, target_content: str, replacement_content: str) -> Dict[str, Any]:
        """Replaces target content chunk with replacement content."""
        start_time = time.time()
        res = self.patcher.patch_file(path, target_content, replacement_content)
        res["tool"] = "apply_patch"
        res["duration_ms"] = int((time.time() - start_time) * 1000)
        return res

    async def delete_file(self, path: str) -> Dict[str, Any]:
        """Deletes file in workspace."""
        start_time = time.time()
        res = self.patcher.delete_file(path)
        res["tool"] = "delete_file"
        res["duration_ms"] = int((time.time() - start_time) * 1000)
        return res

    async def rename_file(self, old_path: str, new_path: str) -> Dict[str, Any]:
        """Renames file in workspace."""
        start_time = time.time()
        res = self.patcher.rename_file(old_path, new_path)
        res["tool"] = "rename_file"
        res["duration_ms"] = int((time.time() - start_time) * 1000)
        return res

    # ─── Command & Test Execution ───────────────────────────────────────────

    async def run_command(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 60,
        allow_network: bool = False,
        network_authorization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Runs a safe shell command inside workspace."""
        from coding.security import NetworkAccessPolicy
        if NetworkAccessPolicy.requires_network_authorization(command) and not network_authorization_id:
            return {
                "success": False,
                "tool": "run_command",
                "command": command,
                "confirmation_required": True,
                "reason": "This command requires outbound network access.",
                "exit_code": -1,
                "stdout": "",
                "stderr": "Outbound network authorization required. Please approve network access before running this command.",
                "duration_ms": 0,
                "timed_out": False,
                "blocked": True
            }

        return await self.executor.run_command(
            command,
            cwd_relative=cwd,
            timeout_seconds=timeout,
            tool_name="run_command",
            allow_network=allow_network or bool(network_authorization_id),
            network_authorization_id=network_authorization_id
        )

    async def run_tests(self, command: str = "npm test", timeout: int = 120) -> Dict[str, Any]:
        """Runs test command (e.g. pytest, npm test, cargo test)."""
        return await self.executor.run_command(command, timeout_seconds=timeout, tool_name="run_tests")

    async def run_linter(self, command: str = "npm run lint", timeout: int = 60) -> Dict[str, Any]:
        """Runs linter (e.g. ruff, eslint, flake8)."""
        return await self.executor.run_command(command, timeout_seconds=timeout, tool_name="run_linter")

    async def run_formatter(self, command: str = "npm run format", timeout: int = 60) -> Dict[str, Any]:
        """Runs code formatter."""
        return await self.executor.run_command(command, timeout_seconds=timeout, tool_name="run_formatter")

    async def run_typecheck(self, command: str = "npm run typecheck", timeout: int = 90) -> Dict[str, Any]:
        """Runs typechecker (e.g. mypy, tsc)."""
        return await self.executor.run_command(command, timeout_seconds=timeout, tool_name="run_typecheck")

    async def run_build(self, command: str = "npm run build", timeout: int = 180) -> Dict[str, Any]:
        """Runs build command."""
        return await self.executor.run_command(command, timeout_seconds=timeout, tool_name="run_build")

    # ─── Git Operations ──────────────────────────────────────────────────────

    async def git_status(self) -> Dict[str, Any]:
        return await self.git.status()

    async def git_diff(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        return await self.git.diff(file_path=file_path)

    async def git_log(self, max_count: int = 10) -> Dict[str, Any]:
        return await self.git.log(max_count=max_count)

    async def git_show(self, commit: str = "HEAD") -> Dict[str, Any]:
        return await self.git.show(commit_or_tag=commit)

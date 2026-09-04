import os
import ast
from typing import Dict, Any, Optional
from coding.security import WorkspaceSecurity, SecurityException

class FilePatcher:
    """Safe, targeted patching and file writes with syntax validation and rollback."""

    def __init__(self, workspace_root: str):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))

    def write_file(self, relative_path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
        """Creates or overwrites a file safely."""
        abs_path = WorkspaceSecurity.resolve_safe_path(self.workspace_root, relative_path)
        if os.path.exists(abs_path) and not overwrite:
            return {"success": False, "error": f"File '{relative_path}' already exists and overwrite is False."}

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        
        # Validation for Python files
        if relative_path.endswith(".py"):
            try:
                ast.parse(content, filename=relative_path)
            except SyntaxError as e:
                return {
                    "success": False,
                    "error": f"Python SyntaxError: {e.msg} at line {e.lineno}",
                    "line": e.lineno
                }

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "success": True,
            "path": relative_path,
            "bytes_written": len(content.encode("utf-8"))
        }

    def patch_file(
        self,
        relative_path: str,
        target_content: str,
        replacement_content: str,
        allow_multiple: bool = False
    ) -> Dict[str, Any]:
        """Replaces exact target_content block with replacement_content."""
        abs_path = WorkspaceSecurity.resolve_safe_path(self.workspace_root, relative_path)
        if not os.path.exists(abs_path):
            return {"success": False, "error": f"File '{relative_path}' does not exist."}

        with open(abs_path, "r", encoding="utf-8") as f:
            original = f.read()

        if target_content not in original:
            return {
                "success": False,
                "error": f"Target content not found in '{relative_path}'."
            }

        count = original.count(target_content)
        if count > 1 and not allow_multiple:
            return {
                "success": False,
                "error": f"Target content matched {count} times in '{relative_path}'. Provide a more specific unique target snippet."
            }

        new_content = original.replace(target_content, replacement_content, 1 if not allow_multiple else -1)

        # Validate syntax if python
        if relative_path.endswith(".py"):
            try:
                ast.parse(new_content, filename=relative_path)
            except SyntaxError as e:
                return {
                    "success": False,
                    "error": f"Patch caused Python SyntaxError: {e.msg} at line {e.lineno}",
                    "line": e.lineno
                }

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {
            "success": True,
            "path": relative_path,
            "replacements": count if allow_multiple else 1
        }

    def delete_file(self, relative_path: str) -> Dict[str, Any]:
        """Deletes a file safely inside the workspace."""
        abs_path = WorkspaceSecurity.resolve_safe_path(self.workspace_root, relative_path)
        if not os.path.exists(abs_path):
            return {"success": False, "error": f"File '{relative_path}' not found."}
        try:
            os.remove(abs_path)
            return {"success": True, "path": relative_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def rename_file(self, old_path: str, new_path: str) -> Dict[str, Any]:
        """Renames a file safely inside the workspace."""
        abs_old = WorkspaceSecurity.resolve_safe_path(self.workspace_root, old_path)
        abs_new = WorkspaceSecurity.resolve_safe_path(self.workspace_root, new_path)
        if not os.path.exists(abs_old):
            return {"success": False, "error": f"Source file '{old_path}' not found."}
        os.makedirs(os.path.dirname(abs_new), exist_ok=True)
        try:
            os.rename(abs_old, abs_new)
            return {"success": True, "old_path": old_path, "new_path": new_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

def validate_python_syntax(content: str, filename: str = "snippet.py") -> bool:
    try:
        ast.parse(content, filename=filename)
        return True
    except SyntaxError:
        return False

def safe_write_file(workspace_root: str, relative_path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
    return FilePatcher(workspace_root).write_file(relative_path, content, overwrite)

def apply_block_patch(workspace_root: str, relative_path: str, target_block: str, replacement_block: str) -> Dict[str, Any]:
    return FilePatcher(workspace_root).patch_file(relative_path, target_block, replacement_block)

import os
import re
import ast
from typing import List, Dict, Any, Optional
from coding.security import WorkspaceSecurity, SecurityException

class CodeSearchEngine:
    """Provides repository-aware textual, regex, and AST symbol navigation."""

    def __init__(self, workspace_root: str):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))

    def find_files(self, pattern: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Finds files matching pattern across workspace."""
        results = []
        regex = re.compile(pattern, re.IGNORECASE) if pattern else None

        for root, dirs, files in os.walk(self.workspace_root):
            # Prune vendor / build directories
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".next", "__pycache__", "venv", ".venv", "dist", "build"}]
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.workspace_root).replace("\\", "/")
                if not regex or regex.search(rel_path) or regex.search(file):
                    results.append({
                        "path": rel_path,
                        "filename": file,
                        "size_bytes": os.path.getsize(os.path.join(root, file))
                    })
                    if len(results) >= max_results:
                        return results
        return results

    def search_text(self, query: str, is_regex: bool = False, file_extension: Optional[str] = None, max_matches: int = 60) -> List[Dict[str, Any]]:
        """Searches for text occurrences across files with line numbers and content."""
        matches = []
        if is_regex:
            try:
                pattern = re.compile(query)
            except re.error as e:
                return [{"error": f"Invalid regex query: {str(e)}"}]
        else:
            query_lower = query.lower()

        for root, dirs, files in os.walk(self.workspace_root):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".next", "__pycache__", "venv", ".venv", "dist", "build"}]
            for file in files:
                if file_extension and not file.endswith(file_extension):
                    continue
                full_path = os.path.join(root, file)
                # Skip large or binary files
                if os.path.getsize(full_path) > 1024 * 1024:
                    continue
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    rel_path = os.path.relpath(full_path, self.workspace_root).replace("\\", "/")
                    for line_no, line in enumerate(lines, start=1):
                        if (is_regex and pattern.search(line)) or (not is_regex and query_lower in line.lower()):
                            matches.append({
                                "file": rel_path,
                                "line_number": line_no,
                                "line_content": line.strip()
                            })
                            if len(matches) >= max_matches:
                                return matches
                except Exception:
                    continue
        return matches

    def extract_symbols_from_file(self, relative_path: str) -> Dict[str, Any]:
        """Extracts AST symbols (classes, functions, methods, imports) from a file."""
        abs_path = WorkspaceSecurity.resolve_safe_path(self.workspace_root, relative_path)
        if not os.path.exists(abs_path):
            return {"error": f"File '{relative_path}' not found."}

        ext = os.path.splitext(abs_path)[1].lower()
        symbols = {"classes": [], "functions": [], "imports": []}

        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if ext in [".py"]:
                tree = ast.parse(content, filename=relative_path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        symbols["classes"].append({
                            "name": node.name,
                            "line": getattr(node, "lineno", 1),
                            "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                        })
                    elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                        symbols["functions"].append({
                            "name": node.name,
                            "line": getattr(node, "lineno", 1),
                            "args": [a.arg for a in node.args.args]
                        })
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            symbols["imports"].append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        symbols["imports"].append(f"{node.module} ({', '.join([a.name for a in node.names])})")
            elif ext in [".js", ".jsx", ".ts", ".tsx"]:
                # Regex extraction for JS/TS
                for match in re.finditer(r"(?:export\s+)?(?:default\s+)?(?:class|function|interface|type)\s+([A-Za-z0-9_]+)", content):
                    sym_name = match.group(1)
                    line_no = content[:match.start()].count("\n") + 1
                    symbols["functions"].append({"name": sym_name, "line": line_no})
                for match in re.finditer(r"(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:\([^)]*\)|[A-Za-z0-9_]+)?\s*=>", content):
                    sym_name = match.group(1)
                    line_no = content[:match.start()].count("\n") + 1
                    symbols["functions"].append({"name": sym_name, "line": line_no})

            return {"file": relative_path, "symbols": symbols}
        except Exception as e:
            return {"file": relative_path, "error": str(e)}

    def find_symbol_definition(self, symbol_name: str) -> List[Dict[str, Any]]:
        """Locates definition of a symbol across workspace."""
        results = []
        target = symbol_name.strip()
        files = self.find_files("")
        for f in files:
            ext = os.path.splitext(f["path"])[1].lower()
            if ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
                sym_info = self.extract_symbols_from_file(f["path"])
                for c in sym_info.get("symbols", {}).get("classes", []):
                    if c["name"].lower() == target.lower():
                        results.append({"type": "class", "file": f["path"], "line": c["line"], "name": c["name"]})
                for fn in sym_info.get("symbols", {}).get("functions", []):
                    if fn["name"].lower() == target.lower():
                        results.append({"type": "function", "file": f["path"], "line": fn["line"], "name": fn["name"]})
        return results

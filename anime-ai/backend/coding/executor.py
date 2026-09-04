"""
Sakura AI — Sandbox Executor Adapter

Provides high-level execution facade over SandboxManager runtimes,
ensuring structured output with success, exit_code, stdout, stderr,
duration_ms, and timed_out flags.
"""

import os
import asyncio
from typing import Dict, Any, Optional, List, Union
from coding.sandbox import SandboxManager, BaseSandboxRuntime

class SandboxExecutor:
    """
    Executes commands and tests in an isolated workspace boundary with
    strict resource timeouts, environment sanitization, and output limits.
    """

    DEFAULT_TIMEOUT_SECONDS = 60

    def __init__(
        self,
        workspace_root: str = ".",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        runtime: Optional[BaseSandboxRuntime] = None
    ):
        self.workspace_root = os.path.realpath(os.path.abspath(workspace_root))
        self.default_timeout_seconds = timeout_seconds
        os.makedirs(self.workspace_root, exist_ok=True)
        self.runtime = runtime or SandboxManager.get_runtime(
            self.workspace_root,
            timeout_seconds=self.default_timeout_seconds
        )

    def execute(
        self,
        command: Union[str, List[str]],
        cwd: Optional[str] = None,
        timeout_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        """Synchronous wrapper for run_command."""
        timeout = timeout_seconds or self.default_timeout_seconds
        return asyncio.run(self.run_command(command, cwd_relative=cwd, timeout_seconds=timeout))

    async def run_command(
        self,
        command: Union[str, List[str]],
        cwd_relative: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        tool_name: str = "run_command",
        allow_network: bool = False
    ) -> Dict[str, Any]:
        """
        Executes a command inside the isolated sandbox boundary.
        Returns structured dictionary guaranteed to contain:
        - success (bool)
        - exit_code (int)
        - stdout (str)
        - stderr (str)
        - duration_ms (int)
        - timed_out (bool)
        """
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds
        res = await self.runtime.run_command(
            command=command,
            cwd_relative=cwd_relative,
            timeout_seconds=timeout,
            tool_name=tool_name,
            allow_network=allow_network
        )
        if "timed_out" not in res:
            res["timed_out"] = False
        return res

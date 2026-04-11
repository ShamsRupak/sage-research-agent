"""
SAGE Code Runner — executes Python snippets in a sandboxed subprocess.

Runs code in a subprocess with a timeout guard to prevent hangs.
Captures stdout, stderr, and return code. This is NOT a secure sandbox
for untrusted code — it's for agent-generated data processing snippets.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import os


async def code_run(snippet: str, timeout: int = 10) -> dict:
    """
    Execute a Python code snippet and return its output.

    Args:
        snippet: Python code to execute
        timeout: Maximum execution time in seconds (default 10)

    Returns:
        Standard result dict with stdout in content.
    """
    if not snippet or not snippet.strip():
        return {
            "success": False,
            "content": "Empty code snippet provided",
            "metadata": {},
        }

    # Write snippet to a temp file
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
            prefix="sage_code_",
        ) as f:
            f.write(snippet)
            temp_path = f.name

        # Run in subprocess
        def _run():
            return subprocess.run(
                ["python", temp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tempfile.gettempdir(),
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run)

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode == 0:
            return {
                "success": True,
                "content": stdout if stdout else "(no output)",
                "metadata": {
                    "return_code": 0,
                    "stderr": stderr,
                },
            }
        else:
            return {
                "success": False,
                "content": f"Code execution error:\n{stderr}",
                "metadata": {
                    "return_code": result.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                },
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "content": f"Code execution timed out after {timeout} seconds",
            "metadata": {"timeout": timeout},
        }
    except Exception as e:
        return {
            "success": False,
            "content": f"Code execution failed: {str(e)}",
            "metadata": {"error": str(e)},
        }
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_path)
        except (OSError, UnboundLocalError):
            pass
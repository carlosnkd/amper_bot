"""
File tools for the ticket pipeline's Coder and Reviewer agents.

Each conversation gets its own workspace directory on disk (workspaces/<conversation_id>/).
Tool functions are plain @tool-decorated callables with no way to receive the current
conversation_id as an argument (the LLM only supplies the args declared in the tool's
signature), so the active workspace is tracked in a ContextVar that TicketFlow sets
before kicking off each crew. This keeps the tool signatures simple for the LLM while
still scoping every read/write to the right conversation.
"""

import contextvars
import subprocess
import sys
from pathlib import Path

from crewai.tools import tool

_active_workspace: contextvars.ContextVar[Path] = contextvars.ContextVar(
    "active_workspace"
)


def set_active_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _active_workspace.set(path)


def resolve_in_workspace(root: Path, relative_path: str) -> Path:
    """
    Resolves `relative_path` against `root`, raising ValueError if it would escape root
    (e.g. via '..' segments or an absolute path). Split out of _resolve() so callers that
    already have a concrete workspace root in hand -- not just the Coder/Reviewer's tools
    running against the ContextVar-scoped "active" workspace -- get the same containment
    guard for free. backend/api/routes.py's GET /workspace_file is the other caller: it
    reads a past build's files back off disk outside of any active crew run, keyed
    directly by conversation_id.
    """
    root = root.resolve()
    target = (root / relative_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(
            f"'{relative_path}' resolves outside the workspace and was rejected."
        )
    return target


def _resolve(relative_path: str) -> Path:
    try:
        root = _active_workspace.get()
    except LookupError as exc:
        raise RuntimeError(
            "No active workspace set -- call set_active_workspace() before running "
            "a crew that uses file tools."
        ) from exc
    return resolve_in_workspace(root, relative_path)


@tool
def write_file(relative_path: str, content: str) -> str:
    """
    Create or overwrite a file inside the ticket workspace.
    relative_path must be relative to the workspace root, e.g. 'src/utils/format.py'.
    Creates any missing parent directories automatically.
    """
    path = _resolve(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {relative_path}"


@tool
def read_file(relative_path: str) -> str:
    """Read the current contents of a file inside the ticket workspace."""
    path = _resolve(relative_path)
    if not path.exists():
        return f"File '{relative_path}' does not exist."
    return path.read_text(encoding="utf-8")


@tool
def list_files() -> str:
    """List every file currently in the ticket workspace, relative to its root."""
    root = _active_workspace.get()
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    return "\n".join(files) if files else "(workspace is empty)"


@tool
def run_python_syntax_check() -> str:
    """
    Compile every .py file in the workspace with py_compile and report any syntax
    errors found. Run this before judging correctness -- it catches broken code cheaply,
    without needing to read every file by hand.
    """
    root = _active_workspace.get()
    py_files = list(root.rglob("*.py"))
    if not py_files:
        return "No Python files found in the workspace."

    errors = []
    for file_path in py_files:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(file_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"{file_path.relative_to(root)}:\n{result.stderr.strip()}")

    return "All files compiled successfully." if not errors else "\n\n".join(errors)

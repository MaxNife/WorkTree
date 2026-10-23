"""Running the CraftApps engines (pdfcraft-cli, wordcraft-cli, gridcraft-cli, deckcraft-cli,
photocraft-cli) as child processes.

An engine's location is an administrator setting (``activities.<engine>_cli`` in config.yaml,
passed to the activity child as ``UAF_CHILD_<ENGINE>_CLI``), never a workflow input, because it
names an executable. Engines run with the run workspace as their folder and receive only
workspace-relative paths that the calling activity has already checked.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

import psutil

from app.domain.masking import get_masker


class EngineMissing(RuntimeError):
    def __init__(self, executable: str, setting: str) -> None:
        super().__init__(
            f"{executable} is not installed: set activities.{setting} in config.yaml "
            f"or put {executable} on PATH"
        )


def find_engine(executable: str, setting: str) -> str:
    """The configured engine path, else the executable on PATH; raises ``EngineMissing``."""
    configured = os.environ.get(f"UAF_CHILD_{setting.upper()}", "")
    if configured:
        if Path(configured).is_file():
            return configured
        raise EngineMissing(executable, setting)
    found = shutil.which(executable)
    if found is None:
        raise EngineMissing(executable, setting)
    return found


def run_engine(
    engine: str,
    args: list[str],
    *,
    workspace: Path,
    timeout: float,
    name: str,
    ok_codes: tuple[int, ...] = (0,),
) -> tuple[int, str]:
    """Run one engine command; returns (exit code, stdout). A code outside ``ok_codes`` raises
    with the engine's message (masked, workspace path removed). Timeouts kill the tree."""
    process = subprocess.Popen(  # noqa: S603 - admin-configured engine, no shell
        [engine, *args],
        cwd=workspace,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(process.pid)
        raise TimeoutError(f"{name} exceeded {timeout:g}s") from None
    if process.returncode not in ok_codes:
        detail = strip_root((stderr or stdout).strip(), workspace)
        raise ValueError(get_masker().mask(detail[-1000:]) or f"{name} exited {process.returncode}")
    return process.returncode, stdout


def strip_root(text: str, root: Path) -> str:
    """Remove the workspace's absolute path (in its common spellings) from engine text, so
    run records never reveal the server's folder layout."""
    resolved = str(root.resolve())
    variants = {resolved, "\\\\?\\" + resolved, resolved.replace("\\", "/"), str(root)}
    for variant in sorted(variants, key=len, reverse=True):
        for form in (variant + "\\", variant + "/", variant):
            text = text.replace(form, "")
            text = text.replace(form.replace("\\", "\\\\"), "")
    return text


def relative(workspace: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()


def kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    for proc in [*children, parent]:
        with contextlib.suppress(psutil.NoSuchProcess):
            proc.kill()
    psutil.wait_procs([*children, parent], timeout=5)

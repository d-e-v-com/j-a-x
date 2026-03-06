#!/usr/bin/env python3
"""prompt_loader.py

Loads agent system prompt templates from files so UI/runner code stays clean.

Templates live under src/prompts/.

Placeholders:
  {role}  - role name (e.g. sysadmin)
  {mode}  - chat | headless
  {tools} - comma-separated tool names
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


DEFAULT_TOOLS = [
    "list_files",
    "read_file",
    "write_file",
    "run_cmd",
    "grep_search",
    "git_status",
    "git_diff",
    "git_stash",
    "git_pop",
    "git_commit",
    "git_push",
    "request_permission",
]


def load_system_prompt(
    repo_root: Path,
    role: str,
    mode: str,
    tools: Iterable[str] = DEFAULT_TOOLS,
) -> str:
    prompts_dir = repo_root / "src" / "prompts"
    base_path = prompts_dir / "system_base.md"
    mode_path = prompts_dir / f"system_{mode}.md"

    parts = []
    if base_path.exists():
        parts.append(base_path.read_text(encoding="utf-8", errors="replace").strip())
    if mode_path.exists():
        parts.append(mode_path.read_text(encoding="utf-8", errors="replace").strip())

    if not parts:
        parts = [
            "### JAX AUTONOMOUS AGENT\n"
            "You are an autonomous agent. Use tools immediately.\n"
            "Never guess paths; use list_files first."
        ]

    merged = "\n\n".join(parts)
    return (
        merged.replace("{role}", role)
        .replace("{mode}", mode)
        .replace("{tools}", ", ".join(list(tools)))
    )

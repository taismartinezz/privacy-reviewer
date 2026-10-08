"""Read-only tools the agent can call to look beyond the diff.

Every tool is confined to the checked-out repository. The agent can read code,
never write it, run it, or reach the network.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

MAX_FILE_CHARS = 20_000
MAX_SEARCH_HITS = 40
SKIP_DIRS = {".git", "node_modules", ".next", "dist", "build", ".venv", "__pycache__", "coverage"}

TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the repository at the PR's head commit. Use this to see "
            "context the diff leaves out, e.g. whether a value is cleared on sign-out or "
            "whether a table has row-level security. Returns numbered lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the repo root."},
                "start_line": {"type": "integer", "description": "First line to return (1-based).", "default": 1},
                "end_line": {"type": "integer", "description": "Last line to return (inclusive)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search the repository for a regular expression (case-insensitive). Returns "
            "matching lines as path:line: text. Use it to find every place a key, column, "
            "or function is used."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regular expression."},
                "path_glob": {"type": "string", "description": "Optional glob to limit files, e.g. 'src/**/*.ts*'."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "submit_review",
        "description": "Submit the final review. Call this exactly once, when you are done investigating.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "One or two sentences on the PR's privacy impact."},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                            "category": {
                                "type": "string",
                                "enum": [
                                    "plaintext-storage",
                                    "access-control",
                                    "data-exposure",
                                    "oauth-scope",
                                    "logging",
                                    "third-party",
                                    "secrets",
                                    "other",
                                ],
                            },
                            "file": {"type": "string"},
                            "line": {"type": "integer"},
                            "title": {"type": "string"},
                            "explanation": {"type": "string", "description": "What could go wrong, for whom, and how."},
                            "suggestion": {"type": "string", "description": "A concrete fix."},
                        },
                        "required": ["severity", "category", "file", "title", "explanation", "suggestion"],
                    },
                },
            },
            "required": ["summary", "findings"],
        },
    },
]


class RepoTools:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()

    def _safe_path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"Path escapes the repository: {rel}")
        return p

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        try:
            p = self._safe_path(path)
        except ValueError as e:
            return f"Error: {e}"
        if not p.is_file():
            return f"Error: file not found: {path}"
        lines = p.read_text(errors="replace").splitlines()
        start = max(1, start_line)
        end = min(len(lines), end_line or len(lines))
        out = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
        if len(out) > MAX_FILE_CHARS:
            out = out[:MAX_FILE_CHARS] + f"\n... [truncated; request a smaller range, file has {len(lines)} lines]"
        return out or "(empty file)"

    def search_code(self, pattern: str, path_glob: str | None = None) -> str:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"Error: invalid regex: {e}"
        hits: list[str] = []
        files = self.root.glob(path_glob) if path_glob else self.root.rglob("*")
        for f in files:
            if not f.is_file() or any(part in SKIP_DIRS for part in f.relative_to(self.root).parts):
                continue
            if f.stat().st_size > 1_000_000:
                continue
            try:
                text = f.read_text(errors="strict")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(self.root)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return "\n".join(hits) + "\n... [more matches; narrow the pattern]"
        return "\n".join(hits) or "No matches."

    def run(self, name: str, args: dict) -> str:
        if name == "read_file":
            return self.read_file(**args)
        if name == "search_code":
            return self.search_code(**args)
        return f"Error: unknown tool {name}"

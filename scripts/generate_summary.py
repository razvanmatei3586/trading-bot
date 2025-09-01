#!/usr/bin/env python3
"""
Generate SUMMARY.md for a GitHub repo with plain-source links (?plain=1).
- Groups important files by category
- Detects GitHub remote and current branch
- Skips vendor/virtualenv/build dirs
"""

from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]

# Folders to ignore during scan
IGNORE_DIRS = {
    ".git", ".github", ".venv", "venv", "env", "__pycache__", "node_modules",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
    ".cache", ".DS_Store"
}

# File globs for categories (ordered)
CATEGORIES: List[Tuple[str, List[str]]] = [
    ("📂 Source Code", ["*.py", "src/**/*.py", "app/**/*.py"]),
    ("📓 Notebooks", ["*.ipynb", "notebooks/**/*.ipynb"]),
    ("🧪 Tests", ["tests/**/*.py", "test_*.py", "*_test.py"]),
    ("📦 Dependencies", ["requirements*.txt", "pyproject.toml", "Pipfile", "Pipfile.lock"]),
    ("⚙️ Config", ["*.yaml", "*.yml", "*.json", "*.toml", ".env*", ".editorconfig"]),
    ("📝 Documentation", ["README.md", "docs/**/*.md", "*.md"]),
    ("🗃️ Git & CI", [".gitignore", ".gitattributes", ".github/workflows/**/*.yml"]),
]

def run(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, cwd=REPO_ROOT).decode().strip()

def detect_remote_https() -> str:
    """
    Return https base like: https://github.com/<user>/<repo>
    Works with both https and ssh origin URLs.
    """
    origin = run(["git", "config", "--get", "remote.origin.url"])
    # Normalize SSH → HTTPS
    # git@github.com:user/repo.git → https://github.com/user/repo
    m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", origin)
    if m:
        return f"https://github.com/{m.group(1)}"
    # https://github.com/user/repo(.git)
    m = re.match(r"https://github\.com/(.+?)(?:\.git)?$", origin)
    if m:
        return f"https://github.com/{m.group(1)}"
    raise RuntimeError(f"Unsupported remote URL: {origin}")

def detect_branch() -> str:
    # Current branch (detached head falls back to 'main')
    try:
        branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch != "HEAD":
            return branch
    except Exception:
        pass
    # Try to read the default branch from remote (optional)
    try:
        ref = run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
        return ref.rsplit("/", 1)[-1]
    except Exception:
        return "main"

def should_ignore(path: Path) -> bool:
    parts = set(path.parts)
    return any(name in IGNORE_DIRS for name in parts)

def glob_many(patterns: List[str]) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        for p in REPO_ROOT.glob(pat):
            if p.is_file() and not should_ignore(p.relative_to(REPO_ROOT)):
                out.append(p.resolve())
    # Stable order
    out = sorted(set(out), key=lambda p: str(p).lower())
    return out

def make_blob_link(base_https: str, branch: str, relpath: str) -> str:
    # Prefer ?plain=1 for clean source view
    return f"{base_https}/blob/{branch}/{relpath}?plain=1"

def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")

def build_index() -> Dict[str, List[Tuple[str, str]]]:
    base = detect_remote_https()
    branch = detect_branch()
    index: Dict[str, List[Tuple[str, str]]] = {}
    seen: set[str] = set()

    for title, patterns in CATEGORIES:
        files = []
        for p in glob_many(patterns):
            rp = rel(p)
            if rp in seen:
                continue
            seen.add(rp)
            files.append((rp, make_blob_link(base, branch, rp)))
        if files:
            index[title] = files
    return index

def render_summary(index: Dict[str, List[Tuple[str, str]]]) -> str:
    lines = []
    lines.append("# Trading Bot – Project Summary\n")
    lines.append("This document lists the main components of the project with direct links for quick review.\n")
    lines.append("Clicking on a link opens the **plain source view** (best for analysis).\n")
    lines.append("\n---\n")

    for title, files in CATEGORIES:
        if title not in index:
            continue
        lines.append(f"\n## {title}\n")
        for rp, link in index[title]:
            display = rp
            lines.append(f"- [{display}]({link})")
    lines.append("\n---\n")
    lines.append("### 🔄 Notes\n")
    lines.append("- This file is auto-generated. Edit `scripts/generate_summary.py` to tweak grouping.\n")
    lines.append("- For review of exact changes, share **commit permalinks** (press `Y` on a file page) in addition to these live links.\n")
    return "\n".join(lines)

def main():
    index = build_index()
    out = render_summary(index)
    (REPO_ROOT / "SUMMARY.md").write_text(out, encoding="utf-8")
    print("SUMMARY.md updated.")

if __name__ == "__main__":
    main()

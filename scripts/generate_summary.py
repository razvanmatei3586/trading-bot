#!/usr/bin/env python3
"""
Generate SUMMARY.md with dual links per file:
- GitHub plain viewer (?plain=1)
- jsDelivr CDN (fallback for reliable fetching)

Also:
- Detects remote + branch automatically
- Skips typical build/venv/cache folders
- Organizes files by categories
"""

from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]

IGNORE_DIRS = {
    ".git", ".github", ".venv", "venv", "env", "__pycache__", "node_modules",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".idea", ".vscode",
    ".cache", ".DS_Store"
}

# (Ordered) sections and their file globs
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
    """Return https base like: https://github.com/<user>/<repo>"""
    origin = run(["git", "config", "remote.origin.url"])
    m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", origin)  # SSH → HTTPS
    if m:
        return f"https://github.com/{m.group(1)}"
    m = re.match(r"https://github\.com/(.+?)(?:\.git)?$", origin)
    if m:
        return f"https://github.com/{m.group(1)}"
    raise RuntimeError(f"Unsupported remote URL: {origin}")

def detect_user_repo(base_https: str) -> str:
    # base_https is https://github.com/<user>/<repo>
    return base_https.rstrip("/").split("github.com/")[1]

def detect_branch() -> str:
    try:
        b = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if b != "HEAD":
            return b
    except Exception:
        pass
    try:
        ref = run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"])
        return ref.rsplit("/", 1)[-1]
    except Exception:
        return "main"

def should_ignore(path: Path) -> bool:
    parts = set(path.parts)
    return any(d in IGNORE_DIRS for d in parts)

def glob_many(patterns: List[str]) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        for p in REPO_ROOT.glob(pat):
            if p.is_file() and not should_ignore(p.relative_to(REPO_ROOT)):
                out.append(p.resolve())
    return sorted(set(out), key=lambda p: str(p).lower())

def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")

def make_github_plain(base_https: str, branch: str, relpath: str) -> str:
    return f"{base_https}/blob/{branch}/{relpath}?plain=1"

def make_jsdelivr_cdn(user_repo: str, branch: str, relpath: str) -> str:
    return f"https://cdn.jsdelivr.net/gh/{user_repo}@{branch}/{relpath}"

def build_index() -> tuple[str, str, str, Dict[str, List[Tuple[str, str, str]]]]:
    """
    Returns (base_https, branch, user_repo, index) where:
    index[section] = list of (relpath, github_plain_url, cdn_url)
    """
    base = detect_remote_https()
    branch = detect_branch()
    user_repo = detect_user_repo(base)
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    seen: set[str] = set()

    for title, patterns in CATEGORIES:
        files: List[Tuple[str, str, str]] = []
        for p in glob_many(patterns):
            rp = rel(p)
            if rp in seen:
                continue
            seen.add(rp)
            gh = make_github_plain(base, branch, rp)
            cdn = make_jsdelivr_cdn(user_repo, branch, rp)
            files.append((rp, gh, cdn))
        if files:
            index[title] = files
    return base, branch, user_repo, index

def render_summary(base: str, branch: str, user_repo: str,
                   index: Dict[str, List[Tuple[str, str, str]]]) -> str:
    lines: List[str] = []
    lines.append("# Trading Bot – Project Summary\n")
    lines.append("This document lists the main components of the project with direct links for quick review.\n")
    lines.append("Each entry has a GitHub **plain** link and a **CDN** fallback (use CDN if GitHub is flaky).\n")
    lines.append("\n---\n")
    lines.append(f"- **Repo:** {base}\n")
    lines.append(f"- **Branch:** `{branch}`\n")
    lines.append(f"- **CDN base:** https://cdn.jsdelivr.net/gh/{user_repo}@{branch}/\n")
    lines.append("\n---\n")

    # Preserve category order defined in CATEGORIES
    for title, _ in CATEGORIES:
        if title not in index:
            continue
        lines.append(f"\n## {title}\n")
        for rp, gh, cdn in index[title]:
            # Example: - path/to/file.py — [GitHub](...) · [CDN](...)
            lines.append(f"- `{rp}` — [GitHub]({gh}) · [CDN]({cdn})")

    lines.append("\n---\n")
    lines.append("### 🔄 Notes\n")
    lines.append("- This file is auto-generated; edit `scripts/generate_summary.py` to change grouping or link styles.\n")
    lines.append("- For exact, immutable references, also share **commit permalinks** (press `Y` on any GitHub file page).\n")
    return "\n".join(lines)

def main():
    base, branch, user_repo, idx = build_index()
    out = render_summary(base, branch, user_repo, idx)
    (REPO_ROOT / "SUMMARY.md").write_text(out, encoding="utf-8")
    print("SUMMARY.md updated with GitHub + CDN links.")

if __name__ == "__main__":
    main()

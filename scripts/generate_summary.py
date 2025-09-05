#!/usr/bin/env python3
"""
Generate SUMMARY.md with primary links to raw.githubusercontent.com.
Also includes optional fallbacks (jsDelivr CDN and GitHub Pages) if you want them.

- Detects remote + branch automatically (works with SSH or HTTPS origins)
- Skips typical build/venv/cache folders
- Organizes files by categories
"""

from __future__ import annotations
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

def detect_user_repo(base_https: str) -> tuple[str, str]:
    # base_https like https://github.com/user/repo
    user, repo = base_https.rstrip("/").split("/")[-2:]
    return user, repo

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

def detect_commit_sha() -> str:
    try:
        return run(["git", "rev-parse", "HEAD"])
    except Exception:
        return ""

def should_ignore(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)

def glob_many(patterns: List[str]) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        for p in REPO_ROOT.glob(pat):
            if p.is_file() and not should_ignore(p.relative_to(REPO_ROOT)):
                out.append(p.resolve())
    return sorted(set(out), key=lambda p: str(p).lower())

def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")

# ---- Link builders ----

def make_raw_link(user: str, repo: str, branch: str, relpath: str) -> str:
    # Primary link: raw.githubusercontent.com (branch-based)
    return f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{relpath}"

def make_raw_link_pinned(user: str, repo: str, sha: str, relpath: str) -> str:
    # Optional immutable link pinned to the exact commit
    return f"https://raw.githubusercontent.com/{user}/{repo}/{sha}/{relpath}"

def make_jsdelivr_cdn(user: str, repo: str, branch: str, relpath: str) -> str:
    # Optional CDN fallback
    return f"https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/{relpath}"

def make_pages_link(user: str, repo: str, relpath: str) -> str:
    # Optional GitHub Pages mirror (requires your Pages workflow/mirror script)
    return f"https://{user}.github.io/{repo}/files/{relpath}"

# -----------------------

def build_index() -> tuple[str, str, str, str, Dict[str, List[Tuple[str, str, str, str]]]]:
    """
    Returns (user, repo, branch, sha, index) where:
    index[section] = list of (relpath, raw_url, cdn_url, pages_url)
    (CDN/Pages may be unused if you prefer only raw.)
    """
    base = detect_remote_https()
    user, repo = detect_user_repo(base)
    branch = detect_branch()
    sha = detect_commit_sha()

    index: Dict[str, List[Tuple[str, str, str, str]]] = {}
    seen: set[str] = set()

    for title, patterns in CATEGORIES:
        files: List[Tuple[str, str, str, str]] = []
        for p in glob_many(patterns):
            rp = rel(p)
            if rp in seen:
                continue
            seen.add(rp)
            raw = make_raw_link(user, repo, branch, rp)
            cdn = make_jsdelivr_cdn(user, repo, branch, rp)
            pages = make_pages_link(user, repo, rp)
            files.append((rp, raw, cdn, pages))
        if files:
            index[title] = files
    return user, repo, branch, sha, index

def render_summary(user: str, repo: str, branch: str, sha: str,
                   index: Dict[str, List[Tuple[str, str, str, str]]]) -> str:
    lines: List[str] = []
    lines.append("# Trading Bot – Project Summary\n")
    lines.append("Primary links use **raw.githubusercontent.com** (best for tools and programmatic reads).\n")
    lines.append("Fallbacks are provided (CDN / Pages) in case a viewer blocks automated clients.\n")
    lines.append("\n---\n")
    lines.append(f"- **Repo:** https://github.com/{user}/{repo}\n")
    lines.append(f"- **Branch:** `{branch}`\n")
    if sha:
        lines.append(f"- **Pinned commit:** `{sha}`  \n")
        lines.append(f"  (Immutable raw example: https://raw.githubusercontent.com/{user}/{repo}/{sha}/PATH/TO/FILE)\n")
    lines.append(f"- **CDN base:** https://cdn.jsdelivr.net/gh/{user}/{repo}@{branch}/\n")
    lines.append(f"- **Pages base (if enabled):** https://{user}.github.io/{repo}/files/\n")
    lines.append("\n---\n")

    # Preserve category order
    for title, _ in CATEGORIES:
        if title not in index:
            continue
        lines.append(f"\n## {title}\n")
        for rp, raw, cdn, pages in index[title]:
            # Example line with multiple links; trim if you only want raw
            lines.append(f"- `{rp}` — [Raw]({raw}) · [CDN]({cdn}) · [Pages]({pages})")

    lines.append("\n---\n")
    lines.append("### 🔄 Notes\n")
    lines.append("- This file is auto-generated; edit `scripts/generate_summary.py` to tweak grouping or links.\n")
    lines.append("- Use **Raw** links for programmatic access. For immutable references, use the **pinned commit** raw URL.\n")
    return "\n".join(lines)

def main():
    user, repo, branch, sha, idx = build_index()
    out = render_summary(user, repo, branch, sha, idx)
    (REPO_ROOT / "SUMMARY.md").write_text(out, encoding="ut

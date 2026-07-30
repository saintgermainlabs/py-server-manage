#!/usr/bin/env python3
"""Audit a Git repository for files that probably belong in .gitignore.

The audit fails when it finds:

* suspicious files staged for commit;
* suspicious untracked files not covered by Git's ignore rules;
* tracked files that now match an ignore rule; or
* a plaintext file beside its encrypted ``.enc`` counterpart.

The script uses Git itself to interpret ignore rules, so nested .gitignore
files, .git/info/exclude, and the user's global excludes are respected.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import PurePosixPath


ALLOWED_BASENAMES = {
    ".env.defaults",
    ".env.example",
    ".env.sample",
    ".env.template",
}

ALLOWED_SUFFIXES = {
    ".age",
    ".enc",
    ".sops",
}

SUSPICIOUS_PATTERNS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.bak",
    "*.backup",
    "*.db",
    "*.jks",
    "*.key",
    "*.keystore",
    "*.log",
    "*.orig",
    "*.p12",
    "*.pem",
    "*.pfx",
    "*.sqlite",
    "*.sqlite3",
    "*.swp",
    "*~",
    "**/credentials.json",
    "**/id_ed25519",
    "**/id_rsa",
    "**/*credentials*.json",
    "**/*secret*.json",
    "**/*secret*.yaml",
    "**/*secret*.yml",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
)

GENERATED_DIRECTORIES = {
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "venv",
}

# Project-specific plaintext outputs. Encrypted versions ending in .enc pass.
PLAINTEXT_INVENTORY_PATTERNS = (
    "data/inventory/*.yaml",
    "data/inventory/*.yml",
    "data/tailscale-api-nodes.yaml",
    "data/tailscale-api-nodes.yml",
    "data/tailscale-api-inventory.yaml",
    "data/tailscale-api-inventory.yml",
    "data/coolify-inventory.yaml",
    "data/coolify-inventory.yml",
    "data/*credentials*.yaml",
    "data/*credentials*.yml",
    "data/*secrets*.yaml",
    "data/*secrets*.yml",
)


class GitError(RuntimeError):
    """Raised when a Git command cannot be completed."""


def run_git(*arguments: str) -> set[str]:
    """Run Git and decode its NUL-separated list of repository paths."""
    result = subprocess.run(
        ["git", *arguments, "-z"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(message or f"git {' '.join(arguments)} failed")

    return {
        value.decode("utf-8", errors="surrogateescape")
        for value in result.stdout.split(b"\0")
        if value
    }


def repository_root() -> str:
    """Return the repository root and fail clearly outside a Git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        raise GitError("not inside a Git repository")
    return result.stdout.strip()


def matches(path: str, pattern: str) -> bool:
    """Match a repository-relative POSIX path against a glob."""
    return fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path).match(pattern)


def is_allowed(path: str) -> bool:
    """Return whether a suspicious-looking filename is explicitly safe."""
    parsed = PurePosixPath(path)
    return (
        parsed.name in ALLOWED_BASENAMES
        or any(path.endswith(suffix) for suffix in ALLOWED_SUFFIXES)
    )


def is_suspicious(path: str) -> bool:
    """Return whether a path looks local, generated, or sensitive."""
    if is_allowed(path):
        return False

    parsed = PurePosixPath(path)
    if any(part in GENERATED_DIRECTORIES for part in parsed.parts):
        return True

    patterns = SUSPICIOUS_PATTERNS + PLAINTEXT_INVENTORY_PATTERNS
    return any(matches(path, pattern) for pattern in patterns)


def plaintext_with_encrypted_copy(
    candidates: set[str], all_known_paths: set[str]
) -> set[str]:
    """Find plaintext candidates that have a sibling named ``<path>.enc``."""
    return {
        path
        for path in candidates
        if not is_allowed(path) and f"{path}.enc" in all_known_paths
    }


def report(title: str, paths: set[str]) -> None:
    """Print a stable, readable finding group."""
    if not paths:
        return
    print(f"\n{title}")
    for path in sorted(paths):
        print(f"  - {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-untracked",
        action="store_true",
        help="do not audit suspicious untracked files",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        repository_root()
        staged = run_git(
            "diff", "--cached", "--name-only", "--diff-filter=ACMR"
        )
        tracked = run_git("ls-files", "--cached")
        untracked = run_git("ls-files", "--others", "--exclude-standard")
        ignored = run_git("ls-files", "--others", "--ignored", "--exclude-standard")
        tracked_and_ignored = run_git(
            "ls-files", "--cached", "--ignored", "--exclude-standard"
        )
    except GitError as error:
        print(f"gitignore audit error: {error}", file=sys.stderr)
        return 2

    all_known_paths = tracked | untracked | ignored
    suspicious_staged = {path for path in staged if is_suspicious(path)}
    suspicious_untracked = (
        set()
        if args.no_untracked
        else {path for path in untracked if is_suspicious(path)}
    )
    plaintext_staged = plaintext_with_encrypted_copy(staged, all_known_paths)
    plaintext_untracked = (
        set()
        if args.no_untracked
        else plaintext_with_encrypted_copy(untracked, all_known_paths)
    )

    report("ERROR: suspicious files are staged:", suspicious_staged)
    report(
        "ERROR: suspicious files are untracked but not ignored:",
        suspicious_untracked,
    )
    report(
        "ERROR: staged plaintext files have encrypted .enc copies:",
        plaintext_staged,
    )
    report(
        "ERROR: untracked plaintext files have encrypted .enc copies:",
        plaintext_untracked,
    )
    report(
        "ERROR: tracked files now match an ignore rule:",
        tracked_and_ignored,
    )

    failed = any(
        (
            suspicious_staged,
            suspicious_untracked,
            plaintext_staged,
            plaintext_untracked,
            tracked_and_ignored,
        )
    )
    if failed:
        print(
            "\nAudit failed. Add an appropriate .gitignore rule, remove the "
            "file from staging, or add a narrow allowlist entry to "
            "scripts/gitignore_audit.py."
        )
        return 1

    print("Gitignore audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

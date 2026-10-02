"""
syntax_guardian.py — Protocol Syntax Guardian (Pre-Commit Code Linter).

Runs before Protocol Shadow (git_push) commits anything: auto-formats
staged/dirty .py files with autopep8 (safe, mechanical PEP-8 fixes only —
whitespace, indentation, line length where possible) and reports any
remaining pycodestyle issues that couldn't be auto-fixed, so they show
up in the commit flow instead of silently going to GitHub.
"""

import subprocess
import sys


def guard_files(filepaths: list) -> dict:
    """Auto-formats each .py file in place with autopep8, then reports
    remaining lint issues via pycodestyle. Returns a summary dict."""
    py_files = [f for f in filepaths if f.endswith(".py")]
    if not py_files:
        return {"formatted": [], "remaining_issues": [], "checked": 0}

    formatted = []
    for f in py_files:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "autopep8", "--in-place", "--aggressive", f],
                capture_output=True, text=True, timeout=20
            )
            if result.returncode == 0:
                formatted.append(f)
        except Exception as e:
            print(f"[Syntax Guardian] autopep8 failed on {f}: {e}")

    remaining_issues = []
    for f in py_files:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pycodestyle", "--max-line-length=120", f],
                capture_output=True, text=True, timeout=20
            )
            if result.stdout.strip():
                issue_lines = result.stdout.strip().split("\n")
                remaining_issues.append({"file": f, "issue_count": len(issue_lines), "sample": issue_lines[:3]})
        except Exception as e:
            print(f"[Syntax Guardian] pycodestyle failed on {f}: {e}")

    return {"formatted": formatted, "remaining_issues": remaining_issues, "checked": len(py_files)}


def summarize_for_speech(guard_result: dict) -> str:
    if guard_result["checked"] == 0:
        return ""
    formatted_count = len(guard_result["formatted"])
    issue_count = len(guard_result["remaining_issues"])
    if issue_count == 0:
        return f"Syntax Guardian cleaned up {formatted_count} files — all PEP-8 clean now. "
    return (f"Syntax Guardian auto-fixed {formatted_count} files, but "
            f"{issue_count} file(s) still have style issues autopep8 couldn't safely fix. ")

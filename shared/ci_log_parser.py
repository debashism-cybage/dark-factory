"""
Parser for raw GitHub Actions job log text, extracting Angular/esbuild
compiler errors in the exact format `ng build` prints them, e.g.:

    2026-08-10T15:36:59.848Z ✘ [ERROR] TS2339: Property 'description' does
    2026-08-10T15:36:59.848Z not exist on type 'Exercise'. [plugin angular-compiler]
    2026-08-10T15:36:59.848Z
    2026-08-10T15:36:59.848Z     src/app/exercises/exercise-card/exercise-card.component.ts:12:20:
    2026-08-10T15:36:59.848Z       12 │       @if (exercise.description) {
    2026-08-10T15:36:59.848Z          ╵                     ~~~~~~~~~~~

Why this exists: the mandatory CI build gate (see
GitHubClient.wait_for_ci_build and agents/development/handler.py's
_run_ci_build_gate) polls the REAL `npx ng build` run in GitHub Actions
rather than re-implementing the Angular toolchain inside this Lambda. A
pass/fail signal alone would satisfy "don't create the PR on failure", but
the build-gate policy also requires "analyze ALL build errors, fix the
underlying code" — this module turns the raw CI log text back into the
same {"file", "issue", "fix"} issue shape the rest of the Development
Agent's fix loop already understands (_attempt_build_fix /
_attempt_create_missing_module), so a real compiler error discovered only
by CI gets the same automated fix treatment as an error this module's own
static checker would have caught.

Deliberately conservative: if the log doesn't match the expected esbuild/ng
error shape, this returns an empty list rather than guessing — callers
should treat "no issues parsed" as "could not extract structured errors
from this log", not "the build actually succeeded" (the CI run's own
conclusion is always the source of truth for pass/fail).
"""

import re

# GitHub Actions job logs prefix every line with an ISO-8601 timestamp.
_TIMESTAMP_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s?", re.MULTILINE
)

# ANSI color escape codes esbuild/ng emit for terminal output.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

# esbuild/Angular compiler error header, e.g.:
#   ✘ [ERROR] TS2339: Property 'description' does not exist on type 'Exercise'. [plugin angular-compiler]
# The message can wrap across multiple raw log lines (each with its own
# timestamp prefix already stripped by the time this runs), so this is
# matched against the WHOLE cleaned text with DOTALL, not line-by-line.
_ERROR_BLOCK_RE = re.compile(
    r"[✘✗xX]\s*\[ERROR\]\s*(?P<message>.+?)(?:\[plugin[^\]]*\]\s*)?\n"
    r"\s*\n"
    r"\s*(?P<path>[\w][\w./-]*\.(?:ts|tsx|html|scss|css|js|jsx))"
    r":(?P<line>\d+):(?P<col>\d+):",
    re.DOTALL,
)

# `Cannot find module 'X'` inside an error message -- lets a CI-discovered
# missing-module error route to the same CREATE-the-file fix path as the
# static checker's own MISSING_MODULE issues, instead of a generic patch
# attempt that could never resolve it (see _attempt_create_missing_module).
_CANNOT_FIND_MODULE_RE = re.compile(r"Cannot find module ['\"]([^'\"]+)['\"]")


def parse_ng_build_errors(log_text: str) -> list[dict[str, str]]:
    """
    Extract structured compiler errors from raw `ng build` CI log text.

    Args:
        log_text: Raw job log text as downloaded from GitHub Actions
            (GitHubClient.get_job_log_text) -- includes per-line timestamp
            prefixes and ANSI color codes, both stripped here.

    Returns:
        List of {"file": ..., "issue": ..., "fix": ""} dicts, one per
        distinct (file, line, message) error found. Additionally carries
        "importingModule" when the message is a "Cannot find module"
        error, so callers can route it the same way as the static
        checker's MISSING_MODULE issues.
    """
    if not log_text:
        return []

    cleaned = _ANSI_ESCAPE_RE.sub("", log_text)
    cleaned = _TIMESTAMP_PREFIX_RE.sub("", cleaned)
    # Collapse the wrapped-message newlines esbuild inserts mid-sentence so
    # the message reads as one line; _ERROR_BLOCK_RE's message group is
    # non-greedy up to the blank-line/path marker so this is safe to do
    # broadly rather than needing to detect wrap points precisely.
    cleaned = re.sub(r"[ \t]*\n[ \t]*(?=\S)", " ", cleaned)

    issues: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for match in _ERROR_BLOCK_RE.finditer(cleaned):
        message = " ".join(match.group("message").split())
        path = match.group("path")
        line_no = match.group("line")

        key = (path, line_no, message)
        if key in seen:
            continue
        seen.add(key)

        issue: dict[str, str] = {
            "file": path,
            "issue": f"{message} (line {line_no})",
            "fix": "",
        }

        module_match = _CANNOT_FIND_MODULE_RE.search(message)
        if module_match:
            issue["kind"] = "MISSING_MODULE"
            issue["importingModule"] = module_match.group(1)

        issues.append(issue)

    return issues

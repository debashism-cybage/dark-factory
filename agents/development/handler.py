"""
Development Agent Lambda Handler.

The Development Agent is a pure Implementer.
It consumes the implementationContract produced by the Planning Agent
and executes it without additional reasoning or repository analysis.

Execution flow:
1. For each file in implementationContract:
   a. Download (MODIFY) or verify absence (CREATE).
   b. Verify SHA256 matches the Planning Agent's hash.
   c. Generate the smallest safe change via Bedrock.
   d. Self-review: verify the change satisfies the ticket.
   e. Commit to GitHub.
2. Create Pull Request.

Build verification is handled by GitHub Actions (npm install, npm run build)
after the PR is created. The Validation Agent consumes that result.

Input: Workflow event with 'planning.implementationContract' (from Planning Agent).
Output: Workflow event enriched with 'artifacts' and status 'DEVELOPMENT_COMPLETE'.
"""

import contextlib
from hashlib import sha256
from typing import Any

from shared.bedrock_client import BedrockClient
from shared.ci_log_parser import parse_ng_build_errors
from shared.config import DevelopmentConfig
from shared.dynamodb_helper import WorkflowTable
from shared.github_client import GitHubClient
from shared.logger import get_logger
from shared.prompts import development as prompts
from shared.s3_helper import S3Helper
from shared.ts_static_check import check_typescript_integrity, expected_missing_path

logger = get_logger(__name__, agent="development")

# Extensions the deterministic TypeScript/Angular static checker applies to.
# Kept narrow on purpose: the checker's import/export/member regexes are only
# meaningful for TS/JS-family source.
_TS_CHECK_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")


# ---------------------------------------------------------------------------
# SHA256 verification
# ---------------------------------------------------------------------------


def _verify_sha256(content: str, expected_hash: str | None) -> bool:
    """
    Verify file content matches the expected SHA256 from the Planning Agent.

    Args:
        content: Current file content from GitHub.
        expected_hash: SHA256 hex digest recorded at planning time.

    Returns:
        True if hash matches or no hash was provided, False if mismatch.
    """
    if not expected_hash:
        return True

    actual_hash = sha256(content.encode("utf-8")).hexdigest()
    return actual_hash == expected_hash


# ---------------------------------------------------------------------------
# Self-review
# ---------------------------------------------------------------------------


def _self_review(
    bedrock: BedrockClient,
    event: dict[str, Any],
    file_entry: dict[str, Any],
    generated_code: str,
    existing_code: str | None,
    protected_files: list[str],
) -> str:
    """
    Perform an AI self-review of the generated code.

    Returns:
        "PASS" or "FAIL: <reason>".
    """
    try:
        result = bedrock.converse(
            system_prompt=prompts.review_system_prompt(),
            user_prompt=prompts.review_user_prompt(
                event=event,
                file_entry=file_entry,
                generated_code=generated_code,
                existing_code=existing_code,
                protected_files=protected_files,
            ),
            max_tokens=512,
        )

        result_stripped = result.strip().upper()
        if result_stripped.startswith("PASS"):
            return "PASS"
        return f"FAIL: {result.strip()}"

    except Exception as ex:
        logger.warning("Self-review failed, defaulting to PASS", error=str(ex))
        return "PASS"


# ---------------------------------------------------------------------------
# Deterministic static check (non-LLM)
# ---------------------------------------------------------------------------


def _run_static_ts_check(
    github: GitHubClient,
    branch: str,
    generated_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Run a deterministic, regex-based cross-reference check over the changeset
    to catch the exact class of errors a real TypeScript compiler flags:
    unresolved relative imports (TS2307), named imports/dynamic-import
    members that don't actually exist on the target module (TS2339), and
    property accesses on injected services that don't match the service's
    real members (TS2339/TS2551).

    This exists because the LLM-based build validation below is a text
    reviewer, not a compiler — it repeatedly misses exactly these mistakes
    (wrong import path, wrong export/member name) because they require
    precise cross-file lookups rather than judgment. This check is grounded
    in real repository file content, not an LLM's read of it, so it runs
    identically and reliably for every ticket.

    Returns:
        List of issues in the same {"file", "issue", "fix"} shape used by
        the LLM-based build validation, so both feed the same auto-fix loop.
    """
    try:
        files_with_content: dict[str, str] = {}
        for f in generated_files:
            path = f["path"]
            with contextlib.suppress(Exception):
                files_with_content[path] = github.get_file_content(path, branch)

        if not files_with_content:
            return []

        try:
            known_paths = {item["path"] for item in github.get_all_files(branch)}
        except Exception:
            known_paths = set()
        known_paths.update(files_with_content.keys())

        def fetch_content(path: str) -> str | None:
            try:
                return github.get_file_content(path, branch)
            except Exception:
                return None

        # Only run the checker's regex machinery against TS/JS files — it's
        # not meaningful for HTML/CSS/JSON/etc.
        ts_files = {p: c for p, c in files_with_content.items() if p.endswith(_TS_CHECK_EXTENSIONS)}
        if not ts_files:
            return []

        issues = check_typescript_integrity(
            files=ts_files,
            known_paths=known_paths,
            fetch_content=fetch_content,
        )

        if issues:
            logger.info("Static TS check found issues", issue_count=len(issues), issues=issues)
        else:
            logger.info("Static TS check PASSED")

        return issues

    except Exception as ex:
        logger.warning("Static TS check failed to execute", error=str(ex))
        return []


# ---------------------------------------------------------------------------
# Build Validation
# ---------------------------------------------------------------------------


def _run_build_validation(
    bedrock: BedrockClient,
    github: GitHubClient,
    branch: str,
    generated_files: list[dict[str, Any]],
    contract_files: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Run cross-file build validation using Bedrock.

    Checks that all imports resolve, modules are declared correctly,
    lazy-loaded routes point to existing files, AND — generically for every
    ticket, not just special-cased ones — that any newly CREATED component is
    actually referenced by the parent file(s) the Planning Agent declared via
    `integratesWith` on the implementationContract. This is what catches a
    component being created but never rendered (e.g. a dashboard tile that
    exists on disk but was never added to the dashboard template).

    Args:
        bedrock: Initialized BedrockClient.
        github: Initialized GitHubClient.
        branch: Feature branch to read fresh content from.
        generated_files: Files successfully generated/modified in this run.
        contract_files: The full implementationContract file list (used to
            look up each CREATE entry's declared `integratesWith` parents so
            their CURRENT content can be fetched and checked).

    Returns:
        List of issues found (empty if all clear).
    """
    try:
        # Get the list of files that were generated/modified
        files_with_content: list[dict[str, Any]] = []
        for f in generated_files:
            path = f["path"]
            try:
                content = github.get_file_content(path, branch)
                files_with_content.append({"path": path, "content": content})
            except Exception:
                pass

        if not files_with_content:
            return []

        # Get existing repository file list for context
        try:
            all_files = github.get_all_files(branch)
            repo_file_paths = [item["path"] for item in all_files]
        except Exception:
            repo_file_paths = []

        # Resolve declared parent/integration files for any CREATE entries so
        # the LLM can check the new component is actually referenced there,
        # instead of just trusting the plan's intent.
        parent_files: list[dict[str, Any]] = []
        if contract_files:
            generated_paths = {f["path"] for f in generated_files}
            parent_paths: set[str] = set()
            for entry in contract_files:
                if entry.get("operation") != "CREATE":
                    continue
                if entry.get("path") not in generated_paths:
                    continue
                for parent_path in entry.get("integratesWith", []) or []:
                    parent_paths.add(parent_path)

            for parent_path in parent_paths:
                try:
                    content = github.get_file_content(parent_path, branch)
                    parent_files.append({"path": parent_path, "content": content})
                except Exception:
                    logger.warning(
                        "Could not fetch declared parent file for integration check",
                        parent_path=parent_path,
                    )

        # Ask Bedrock to validate
        result = bedrock.converse_json(
            system_prompt=prompts.build_validation_system_prompt(),
            user_prompt=prompts.build_validation_user_prompt(
                generated_files=files_with_content,
                repository_files=repo_file_paths,
                parent_files=parent_files or None,
            ),
            max_tokens=2048,
        )

        if result.get("status") == "FAIL":
            issues = result.get("issues", [])
            logger.info("Build validation found issues", issues=issues)
            return issues

        logger.info("Build validation PASSED")
        return []

    except Exception as ex:
        logger.warning("Build validation failed to execute", error=str(ex))
        return []


_INTEGRATION_ISSUE_MARKERS = (
    "not integrated into any parent",
    "never injected",
    "never used",
    "never imported",
    "never called",
    "created but not",
)


def _redirect_integration_issue_to_parent(
    issue: dict[str, Any],
    contract_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Correct a common LLM mistake in build-validation issues: reporting a
    "component/service created but never wired into its parent" problem
    against the CHILD file's path instead of the PARENT file that is
    actually missing the import/injection/selector usage.

    Why this matters: `_attempt_build_fix` (and its caller) blindly rewrite
    whichever path is in issue["file"]. If that's the child, the fix loop
    repeatedly regenerates an already-correct file while the real broken
    parent (e.g. the page component that never imports the child or never
    calls the service) is left completely untouched — this is exactly what
    happened on SCRUM-10 and SCRUM-14: `recipe-card.ts`/`exercise-card.ts`
    got "fixed" three times each while `recipes.ts`/`exercises.ts` — the
    file that actually needed the import and the API call — was never
    touched by the fix loop at all.

    This is a deterministic backstop for when the LLM doesn't follow the
    build-validation prompt's instruction to report the parent: if the
    issue text matches an integration-failure pattern AND the implementation
    contract declares an `integratesWith` parent for the reported file, the
    issue is redirected to that parent path instead.

    Args:
        issue: A single issue dict from build validation (static or LLM).
        contract_files: The full implementationContract file list, used to
            look up the reported file's declared `integratesWith` parent.

    Returns:
        The issue dict, with "file" replaced by the parent path if this was
        an integration-failure issue reported against a child with a known
        parent. Otherwise returned unchanged.
    """
    issue_text = (issue.get("issue", "") or "").lower()
    if not any(marker in issue_text for marker in _INTEGRATION_ISSUE_MARKERS):
        return issue

    reported_path = issue.get("file", "")
    for entry in contract_files:
        if entry.get("path") != reported_path:
            continue
        if entry.get("operation") != "CREATE":
            continue
        parents = entry.get("integratesWith") or []
        if not parents:
            continue
        parent_path = parents[0]
        if parent_path == reported_path:
            continue
        logger.info(
            "Redirecting integration-failure issue from child to its declared parent",
            child=reported_path,
            parent=parent_path,
            issue=issue.get("issue", ""),
        )
        redirected = dict(issue)
        redirected["file"] = parent_path
        return redirected

    return issue


def _attempt_create_missing_module(
    bedrock: BedrockClient,
    github: GitHubClient,
    branch: str,
    event: dict[str, Any],
    issue: dict[str, Any],
    ticket_id: str,
    validation_checklist: list[str],
) -> dict[str, Any] | None:
    """
    Fix a MISSING_MODULE issue by CREATING the missing dependency file,
    instead of patching the file that imports it.

    Why this exists: `_attempt_build_fix` (below) only ever rewrites the
    *importing* file. When the real problem is "the imported file was never
    planned or generated" (e.g. a component imports a sibling component that
    the Planning Agent's contract never listed), patching the importer can
    only ever toggle which nonexistent path it points at — it can never make
    the target exist. This is exactly what happened on SCRUM-10: two
    successive auto-fix commits just swapped the broken import path between
    two equally-nonexistent files, then gave up after max_fix_rounds and
    shipped the PR with a still-broken import.

    Args:
        issue: Dict from ts_static_check with kind="MISSING_MODULE",
            "expectedPath", "requiredExports", "importingModule", plus the
            usual "file"/"issue"/"fix" keys.

    Returns:
        File entry dict if the missing file was created, None if it
        couldn't be (e.g. Bedrock failed, or the path already exists so
        this isn't really a missing-module situation).
    """
    importing_file = issue.get("file", "")
    expected_path = issue.get("expectedPath", "")
    required_exports = issue.get("requiredExports", []) or []
    importing_module = issue.get("importingModule", "")

    if not importing_file or not expected_path:
        return None

    # Guard against acting on stale info: if the path already exists (e.g. a
    # previous fix round already created it), this isn't a missing-module
    # case anymore — let the normal re-validation pass judge it instead of
    # overwriting a file that might now be correct.
    if github.file_exists(expected_path, branch) or github.file_exists(expected_path):
        logger.info(
            "Missing-module target already exists, skipping create",
            expected_path=expected_path,
        )
        return None

    logger.info(
        "Creating missing dependency file",
        importing_file=importing_file,
        expected_path=expected_path,
        required_exports=required_exports,
    )

    try:
        try:
            importer_content = github.get_file_content(importing_file, branch)
        except Exception:
            importer_content = ""

        create_prompt = (
            f"A file imports from '{importing_module}' but that file does not exist yet "
            f"in the repository. Create it.\n\n"
            f"Missing file to create: {expected_path}\n"
            f"It must export: {', '.join(required_exports) if required_exports else '(match what the importer expects)'}\n\n"
            f"FILE THAT IMPORTS IT ({importing_file}):\n\n{importer_content}\n\n"
            f"Create a complete, minimal, working implementation of {expected_path} that:\n"
            f"- Exports exactly the name(s) listed above (match spelling/case exactly).\n"
            f"- Is consistent with how it is used in the importing file shown above "
            f"(e.g. if used as an Angular component with a selector in a template, "
            f"create a real standalone Angular component; if used as a service, create "
            f"an @Injectable service; if used as a guard, create a CanActivateFn).\n"
            f"- Follows standard Angular/TypeScript conventions for this kind of file.\n"
            f"- Compiles on its own (correct imports, no missing types).\n\n"
            f"Return ONLY the complete file contents for {expected_path}.\n"
            f"Do not wrap in markdown. Do not use code fences. Do not explain."
        )

        created_code = bedrock.converse(
            system_prompt=prompts.system_prompt(),
            user_prompt=create_prompt,
            max_tokens=8192,
        )

        commit_msg = f"fix({ticket_id}): create missing dependency {expected_path}"
        github.commit_file(
            branch=branch,
            path=expected_path,
            content=created_code,
            message=commit_msg,
        )

        logger.info("Missing dependency file created", expected_path=expected_path)

        return {
            "path": expected_path,
            "operation": "BUILD_FIX",
            "status": "SUCCESS",
            "size": len(created_code),
            "issue": issue.get("issue", ""),
        }

    except Exception as ex:
        logger.error(
            "Failed to create missing dependency file",
            expected_path=expected_path,
            error=str(ex),
        )
        return None


def _attempt_build_fix(
    bedrock: BedrockClient,
    github: GitHubClient,
    branch: str,
    event: dict[str, Any],
    issue: dict[str, Any],
    ticket_id: str,
    validation_checklist: list[str],
) -> dict[str, Any] | None:
    """
    Attempt to fix a build issue found during validation.

    Args:
        issue: Dict with 'file', 'issue', 'fix' keys.

    Returns:
        File entry dict if fixed, None if fix failed.
    """
    file_path = issue.get("file", "")
    issue_desc = issue.get("issue", "")
    suggested_fix = issue.get("fix", "")

    if not file_path:
        return None

    logger.info(
        "Attempting build fix",
        file_path=file_path,
        issue=issue_desc,
    )

    try:
        # Get current file content
        try:
            existing_code = github.get_file_content(file_path, branch)
        except Exception:
            try:
                existing_code = github.get_file_content(file_path)
            except Exception:
                logger.warning("Cannot read file for build fix", file_path=file_path)
                return None

        # Generate fix
        fix_prompt = (
            f"Fix this compilation error in the file.\n\n"
            f"File: {file_path}\n"
            f"Error: {issue_desc}\n"
            f"Suggested fix: {suggested_fix}\n\n"
            f"CURRENT FILE:\n\n{existing_code}\n\n"
            f"Apply ONLY the fix for this specific error. "
            f"Do NOT change anything else. "
            f"Return the COMPLETE fixed file contents.\n"
            f"Do not wrap in markdown. Do not use code fences. Do not explain."
        )

        fixed_code = bedrock.converse(
            system_prompt=prompts.system_prompt(),
            user_prompt=fix_prompt,
            max_tokens=8192,
        )

        # Commit the fix
        commit_msg = f"fix({ticket_id}): resolve build error in {file_path}"
        github.commit_file(
            branch=branch,
            path=file_path,
            content=fixed_code,
            message=commit_msg,
        )

        logger.info("Build fix committed", file_path=file_path)

        return {
            "path": file_path,
            "operation": "BUILD_FIX",
            "status": "SUCCESS",
            "size": len(fixed_code),
            "issue": issue_desc,
        }

    except Exception as ex:
        logger.error("Build fix failed", file_path=file_path, error=str(ex))
        return None


# ---------------------------------------------------------------------------
# Mandatory PR build gate
# ---------------------------------------------------------------------------

# Max number of fix -> push -> re-poll cycles before giving up and reporting
# failure instead of creating a PR. Deliberately smaller than the internal
# static/LLM build-validation loop's own max_fix_rounds, since each round
# here costs a real CI run (minutes), not a Bedrock call (seconds).
#
# Budget note: this Lambda's own execution timeout must be able to fit
# (1 + _MAX_CI_GATE_FIX_ROUNDS) poll cycles of up to _CI_BUILD_TIMEOUT_SECONDS
# each, plus the Bedrock/GitHub calls each fix round makes. At 2 rounds x
# 240s = 480s of polling plus fix overhead, the Lambda timeout must be
# raised well above its previous 300s default -- see deploy.sh /
# infrastructure config, which must set this function's timeout close to
# Lambda's hard maximum (900s) for this gate to have any real headroom.
_MAX_CI_GATE_FIX_ROUNDS = 2

# How long to wait for one CI run to complete before treating it as a
# timeout. angular-dev's pr-build-check.yml is a single `npm ci && ng build`
# job on ubuntu-latest with npm caching -- comfortably under 3 minutes in
# practice. Kept well under the per-round Lambda time budget (see above) so
# multiple rounds can still fit inside one invocation.
_CI_BUILD_TIMEOUT_SECONDS = 240


def _run_ci_build_gate(
    bedrock: BedrockClient,
    github: GitHubClient,
    branch: str,
    event: dict[str, Any],
    ticket_id: str,
    contract_files: list[dict[str, Any]],
    validation_checklist: list[str],
    generated_files: list[dict[str, Any]],
    config: DevelopmentConfig,
) -> dict[str, Any]:
    """
    MANDATORY PR BUILD GATE.

    A PR may be created ONLY after the repository's own CI build-check
    workflow (the exact `npx ng build --configuration production ...`
    command, executed by GitHub Actions -- not simulated here, since this
    Lambda has no Node.js/Angular toolchain) reports success for the commit
    being shipped.

    That workflow (pr-build-check.yml) triggers `on: pull_request`, so a PR
    must exist for it to run at all. This opens the PR as a DRAFT first —
    satisfying the trigger — polls the real build result, and only then
    either promotes it to ready-for-review (pass) or closes it and reports
    the failure in full (exhausted all fix rounds without a pass). No
    exceptions: on any outcome other than a clean pass within
    _MAX_CI_GATE_FIX_ROUNDS, this returns passed=False and the caller MUST
    NOT create/keep open a non-draft PR.

    Sequence per round:
        push already happened (either the initial commits, or a prior
        round's fix commits)
            -> ensure a draft PR exists (first round) so the workflow has
               something to trigger against
            -> poll wait_for_ci_build for that PR's head commit
            -> SUCCESS: done, return passed=True
            -> FAILURE: download the failing job's log, parse real
               `ng build` errors, run them through the SAME fix primitives
               used by the internal build-validation loop
               (_attempt_create_missing_module / _attempt_build_fix), push
               the fixes, loop
            -> TIMEOUT/NOT_FOUND: treated as a failed round (can't confirm
               success, so PR_READY cannot be true) but does not consume a
               fix round the same way, since there's nothing concrete to
               fix -- retried once, then reported as a blocker

    Returns:
        {
            "passed": bool,
            "reason": str,
            "buildErrors": list[dict],
            "generatedFiles": list[dict],  # possibly extended with fixes
            "prNumber": int | None,
            "prUrl": str | None,
            "prIsDraft": bool,
            "runUrl": str | None,
            "fixRounds": int,
        }
    """
    workflow_file = config.ci_build_workflow_file
    pr: dict[str, Any] | None = None
    last_build_errors: list[dict[str, Any]] = []
    last_run_url: str | None = None

    for fix_round in range(_MAX_CI_GATE_FIX_ROUNDS + 1):
        commit_sha = github.get_branch_head_sha(branch)

        if pr is None:
            pr = github.ensure_pull_request(
                branch=branch,
                ticket_id=ticket_id,
                workflow_id=event.get("workflowId", ""),
                draft=True,
            )
            logger.info(
                "Opened draft PR to trigger mandatory CI build gate",
                pr_number=pr["number"],
                commit_sha=commit_sha,
            )

        result = github.wait_for_ci_build(
            commit_sha=commit_sha,
            workflow_file=workflow_file,
            timeout_seconds=_CI_BUILD_TIMEOUT_SECONDS,
        )
        last_run_url = result.get("runUrl") or last_run_url

        if result["outcome"] == "SUCCESS":
            logger.info(
                "MANDATORY BUILD GATE PASSED",
                commit_sha=commit_sha,
                run_url=result.get("runUrl"),
                fix_rounds=fix_round,
            )
            return {
                "passed": True,
                "reason": "CI_BUILD_SUCCEEDED",
                "buildErrors": [],
                "generatedFiles": generated_files,
                "prNumber": pr["number"],
                "prUrl": pr["url"],
                "prIsDraft": True,
                "runUrl": result.get("runUrl"),
                "fixRounds": fix_round,
            }

        if result["outcome"] in ("TIMEOUT", "NOT_FOUND"):
            logger.warning(
                "CI build gate could not confirm a result this round",
                outcome=result["outcome"],
                commit_sha=commit_sha,
            )
            last_build_errors = [
                {
                    "file": "",
                    "issue": (
                        f"Could not confirm the CI build result for commit {commit_sha} "
                        f"(outcome: {result['outcome']}). The workflow may not have "
                        f"triggered, or took longer than {_CI_BUILD_TIMEOUT_SECONDS}s."
                    ),
                    "fix": "",
                }
            ]
            continue

        # outcome == "FAILURE" -- fetch the real compiler errors and fix them.
        run_id = result.get("runId")
        log_text = github.get_failed_job_log_text(run_id) if run_id else None
        build_errors = parse_ng_build_errors(log_text or "")

        if not build_errors:
            # Build failed but the log couldn't be parsed into structured
            # errors (e.g. unexpected format, or a non-compiler failure
            # like a network error in npm ci). Nothing concrete to fix
            # automatically -- report the raw situation rather than guess.
            build_errors = [
                {
                    "file": "",
                    "issue": (
                        f"CI build failed for commit {commit_sha} but its errors could "
                        f"not be parsed from the job log. See {result.get('runUrl')} "
                        f"for the raw output."
                    ),
                    "fix": "",
                }
            ]

        last_build_errors = build_errors
        logger.warning(
            "MANDATORY BUILD GATE: CI build FAILED, attempting fixes",
            fix_round=fix_round,
            error_count=len(build_errors),
            run_url=result.get("runUrl"),
        )

        if fix_round == _MAX_CI_GATE_FIX_ROUNDS:
            break

        for issue in build_errors:
            if issue.get("kind") == "MISSING_MODULE" and issue.get("file"):
                issue["expectedPath"] = expected_missing_path(
                    issue["file"], issue["importingModule"]
                )
                issue.setdefault("requiredExports", [])
                fixed = _attempt_create_missing_module(
                    bedrock=bedrock,
                    github=github,
                    branch=branch,
                    event=event,
                    issue=issue,
                    ticket_id=ticket_id,
                    validation_checklist=validation_checklist,
                )
            elif issue.get("file"):
                issue = _redirect_integration_issue_to_parent(issue, contract_files)
                fixed = _attempt_build_fix(
                    bedrock=bedrock,
                    github=github,
                    branch=branch,
                    event=event,
                    issue=issue,
                    ticket_id=ticket_id,
                    validation_checklist=validation_checklist,
                )
            else:
                fixed = None

            if fixed:
                generated_files.append(fixed)

    # Exhausted all fix rounds without a passing build.
    logger.error(
        "MANDATORY BUILD GATE: exhausted all fix rounds, CI build never passed",
        fix_rounds=_MAX_CI_GATE_FIX_ROUNDS,
        remaining_errors=last_build_errors,
    )

    if pr is not None:
        error_summary = "\n".join(f"- {e.get('file', '(unknown file)')}: {e['issue']}" for e in last_build_errors)
        github.close_pull_request(
            pr["number"],
            comment=(
                "Dark Factory closed this draft PR: the mandatory production "
                f"build (`npx ng build --configuration production ...`) did not "
                f"pass after {_MAX_CI_GATE_FIX_ROUNDS} automated fix attempts.\n\n"
                f"Remaining build errors:\n{error_summary}\n\n"
                f"Last CI run: {last_run_url or '(unavailable)'}"
            ),
        )

    return {
        "passed": False,
        "reason": "CI_BUILD_NEVER_PASSED",
        "buildErrors": last_build_errors,
        "generatedFiles": generated_files,
        "prNumber": pr["number"] if pr else None,
        "prUrl": pr["url"] if pr else None,
        "prIsDraft": True,
        "runUrl": last_run_url,
        "fixRounds": _MAX_CI_GATE_FIX_ROUNDS,
    }


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Development agent entry point."""
    logger.info("Development agent started", workflow_id=event.get("workflowId"))

    config = DevelopmentConfig()

    workflow_id = event["workflowId"]
    ticket_id = event["ticketId"]
    planning = event["planning"]

    # Extract implementation contract
    contract = planning.get("implementationContract", {})
    contract_files = contract.get("files", [])
    protected_files = contract.get("protectedFiles", [])
    validation_checklist = contract.get("validationChecklist", [])

    if not contract_files:
        logger.warning(
            "No files in implementationContract, nothing to implement",
            workflow_id=workflow_id,
        )
        event["status"] = "DEVELOPMENT_COMPLETE"
        event["currentAgent"] = "development"
        event["artifacts"] = {"generatedFiles": [], "skipped": True}
        return event

    # Initialize services
    github = GitHubClient(
        owner=config.github_repo_owner,
        repo=config.github_repo_name,
        secret_name=config.github_secret_name,
    )
    bedrock = BedrockClient(config.bedrock_model_id)
    s3 = S3Helper(config.bucket_name)
    table = WorkflowTable(config.table_name)

    # Create feature branch. If it already exists, ensure_branch either:
    #   - resets it to main's tip (if its previous PR was already merged --
    #     prevents stacking new work onto history main no longer wants,
    #     which is what produced unresolvable conflicts on feature/SCRUM-16), or
    #   - syncs it with the latest main (if it's still mid-flight, e.g. an
    #     adaptive-replan retry), so it never silently drifts from main
    #     across retries.
    # See GitHubClient.ensure_branch for the full decision logic.
    branch = f"feature/{ticket_id}"
    branch_sync_result = github.ensure_branch(branch)
    if branch_sync_result and branch_sync_result.get("conflict"):
        logger.warning(
            "Feature branch has a real merge conflict with main — "
            "continuing with existing branch content; PR will likely need "
            "manual conflict resolution",
            workflow_id=workflow_id,
            branch=branch,
        )
    elif branch_sync_result and branch_sync_result.get("action") == "reset":
        logger.info(
            "Feature branch was reset to latest main (previous PR already merged)",
            workflow_id=workflow_id,
            branch=branch,
        )

    # Execute each file in the contract
    generated_files: list[dict[str, Any]] = []
    last_commit: dict[str, Any] | None = None
    aborted = False
    abort_reason = ""

    logger.info(
        "Executing implementation contract",
        workflow_id=workflow_id,
        file_count=len(contract_files),
        protected_count=len(protected_files),
    )

    for file_entry in contract_files:
        file_path = file_entry["path"]
        operation = file_entry.get("operation", "MODIFY")
        expected_hash = file_entry.get("sha256")
        expected_changes = file_entry.get("expectedChanges", [])

        logger.info("Processing file", file_path=file_path, operation=operation)

        # ---------------------------------------------------------------
        # Step 1: Download current file (MODIFY) or verify absence (CREATE)
        # ---------------------------------------------------------------
        existing_code: str | None = None

        if operation == "MODIFY":
            try:
                existing_code = github.get_file_content(file_path, branch)
            except Exception:
                try:
                    existing_code = github.get_file_content(file_path)
                except Exception as ex:
                    logger.error(
                        "Cannot download file for MODIFY, aborting",
                        file_path=file_path,
                        error=str(ex),
                    )
                    aborted = True
                    abort_reason = f"FILE_NOT_FOUND: {file_path}"
                    break

            # ---------------------------------------------------------------
            # Step 2: Verify SHA256
            # ---------------------------------------------------------------
            if not _verify_sha256(existing_code, expected_hash):
                logger.warning(
                    "SHA256 mismatch — file changed since planning",
                    file_path=file_path,
                    expected_hash=expected_hash,
                )
                generated_files.append(
                    {
                        "path": file_path,
                        "operation": operation,
                        "status": "SHA_MISMATCH",
                    }
                )
                aborted = True
                abort_reason = f"FILE_CHANGED_REPLAN_REQUIRED: {file_path}"
                break

        elif operation == "CREATE":
            if github.file_exists(file_path, branch) or github.file_exists(file_path):
                logger.warning(
                    "File already exists for CREATE, switching to MODIFY",
                    file_path=file_path,
                )
                operation = "MODIFY"
                try:
                    existing_code = github.get_file_content(file_path)
                except Exception:
                    existing_code = None

        # ---------------------------------------------------------------
        # Step 3: Generate implementation
        # ---------------------------------------------------------------
        sys_prompt = prompts.system_prompt()

        if operation == "MODIFY":
            user_msg = prompts.user_prompt_modify(
                event=event,
                file_path=file_path,
                existing_content=existing_code or "",
                expected_changes=expected_changes,
                validation_checklist=validation_checklist,
            )
        else:
            user_msg = prompts.user_prompt_create(
                event=event,
                file_path=file_path,
                expected_changes=expected_changes,
                validation_checklist=validation_checklist,
            )

        logger.info("Generating implementation", file_path=file_path, operation=operation)
        generated_code = bedrock.converse(
            system_prompt=sys_prompt,
            user_prompt=user_msg,
            max_tokens=8192,
        )

        # ---------------------------------------------------------------
        # Step 4: Self-review
        # ---------------------------------------------------------------
        review_result = _self_review(
            bedrock=bedrock,
            event=event,
            file_entry=file_entry,
            generated_code=generated_code,
            existing_code=existing_code,
            protected_files=protected_files,
        )

        if review_result != "PASS":
            logger.warning(
                "Self-review FAILED, attempting regeneration",
                file_path=file_path,
                review_result=review_result,
            )

            # Retry up to 2 times, feeding back the SPECIFIC review failure
            # each time (not just re-running the identical prompt, which
            # reliably reproduces the identical failure — this is exactly
            # what happened on SCRUM-10/SCRUM-14: the LLM's output was
            # truncated mid-method, the retry used the same prompt with no
            # mention of truncation, and it truncated again).
            max_regen_attempts = 2
            for attempt in range(1, max_regen_attempts + 1):
                retry_msg = (
                    f"{user_msg}\n\n"
                    f"--------------------------------------------------\n"
                    f"PREVIOUS ATTEMPT REJECTED (attempt {attempt}/{max_regen_attempts})\n"
                    f"--------------------------------------------------\n"
                    f"Your previous response failed review for this reason:\n"
                    f"{review_result}\n\n"
                    f"Fix this specific problem. If the previous response was cut off "
                    f"or incomplete, make sure this response is the COMPLETE file from "
                    f"start to finish, including the closing brace/tag and every method "
                    f"body fully implemented — do not stop partway through."
                )

                generated_code = bedrock.converse(
                    system_prompt=sys_prompt,
                    user_prompt=retry_msg,
                    max_tokens=8192,
                )

                review_result = _self_review(
                    bedrock=bedrock,
                    event=event,
                    file_entry=file_entry,
                    generated_code=generated_code,
                    existing_code=existing_code,
                    protected_files=protected_files,
                )

                if review_result == "PASS":
                    break

            if review_result != "PASS":
                # This file is a hard failure, not a soft skip. Silently
                # "continuing" here is exactly what shipped SCRUM-10 and
                # SCRUM-14 broken: the hub page file that wires the API/
                # service/component together failed review and got skipped,
                # leaving the original placeholder in the PR with no visible
                # signal until a human clicked through GitHub Actions. Abort
                # the whole run instead so the workflow surfaces as a clear
                # failure state rather than a silently-incomplete PR.
                logger.error(
                    "Self-review FAILED after all retries, aborting workflow "
                    "rather than shipping a PR with this file left unimplemented",
                    file_path=file_path,
                    review_result=review_result,
                )
                generated_files.append(
                    {
                        "path": file_path,
                        "operation": operation,
                        "status": "REVIEW_FAILED",
                        "reason": review_result,
                    }
                )
                aborted = True
                abort_reason = f"REVIEW_FAILED_UNRECOVERABLE: {file_path}: {review_result}"
                break

        # ---------------------------------------------------------------
        # Step 5: Commit to GitHub
        # ---------------------------------------------------------------
        commit_msg = f"feat({ticket_id}): {operation.lower()} {file_path}"
        last_commit = github.commit_file(
            branch=branch,
            path=file_path,
            content=generated_code,
            message=commit_msg,
        )

        generated_files.append(
            {
                "path": file_path,
                "operation": operation,
                "status": "SUCCESS",
                "size": len(generated_code),
                "review": "PASS",
            }
        )

        logger.info("File committed", file_path=file_path, operation=operation)

    # -----------------------------------------------------------------------
    # Handle abort — structured response for adaptive replanning
    # -----------------------------------------------------------------------
    if aborted:
        # Track which files had SHA mismatches
        changed_files = [f["path"] for f in generated_files if f.get("status") == "SHA_MISMATCH"]

        # If abort was due to file change, return REPLAN_REQUIRED
        if "FILE_CHANGED" in abort_reason or "REPLAN" in abort_reason:
            replan_attempt = event.get("replanAttempt", 0)

            if replan_attempt >= 3:
                logger.error(
                    "Max replan attempts reached, manual review required",
                    workflow_id=workflow_id,
                    replan_attempt=replan_attempt,
                )

                table.update_status(
                    workflow_id=workflow_id,
                    status="MANUAL_REVIEW_REQUIRED",
                    agent="development",
                    artifacts={
                        "reason": "MAX_REPLAN_ATTEMPTS_EXCEEDED",
                        "replanAttempt": replan_attempt,
                        "changedFiles": changed_files,
                        "generatedFiles": generated_files,
                    },
                )

                event["status"] = "MANUAL_REVIEW_REQUIRED"
                event["currentAgent"] = "development"
                event["artifacts"] = {
                    "reason": "MAX_REPLAN_ATTEMPTS_EXCEEDED",
                    "replanAttempt": replan_attempt,
                    "changedFiles": changed_files,
                    "generatedFiles": generated_files,
                }
                return event

            # Return structured REPLAN_REQUIRED for Step Functions Choice
            logger.info(
                "Repository drift detected, requesting adaptive replan",
                workflow_id=workflow_id,
                changed_files=changed_files,
                replan_attempt=replan_attempt + 1,
            )

            # Build recovery history entry for this attempt
            recovery_entry = {
                "attempt": replan_attempt + 1,
                "reason": "SHA_MISMATCH",
                "changedFiles": changed_files,
                "status": "REPLANNING",
            }

            # Append to existing recovery history
            recovery_history = event.get("recoveryHistory", [])
            recovery_history.append(recovery_entry)

            table.update_status(
                workflow_id=workflow_id,
                status="REPLAN_REQUIRED",
                agent="development",
                artifacts={
                    "reason": "FILE_CHANGED",
                    "changedFiles": changed_files,
                    "replanAttempt": replan_attempt + 1,
                    "generatedFiles": generated_files,
                    "recoveryHistory": recovery_history,
                },
            )

            event["status"] = "REPLAN_REQUIRED"
            event["currentAgent"] = "development"
            event["replanAttempt"] = replan_attempt + 1
            event["changedFiles"] = changed_files
            event["originalContract"] = contract
            event["replanBranch"] = branch
            event["recoveryHistory"] = recovery_history
            event["artifacts"] = {
                "reason": "FILE_CHANGED",
                "changedFiles": changed_files,
                "replanAttempt": replan_attempt + 1,
                "generatedFiles": generated_files,
                "recoveryHistory": recovery_history,
                "branch": branch,
            }
            return event

        # Non-file-change abort (other errors)
        logger.error("Implementation aborted", workflow_id=workflow_id, reason=abort_reason)

        table.update_status(
            workflow_id=workflow_id,
            status="DEVELOPMENT_ABORTED",
            agent="development",
            artifacts={"reason": abort_reason, "generatedFiles": generated_files},
        )

        event["status"] = "DEVELOPMENT_ABORTED"
        event["currentAgent"] = "development"
        event["artifacts"] = {"reason": abort_reason, "generatedFiles": generated_files}
        return event

    # -----------------------------------------------------------------------
    # Build Validation: Cross-file compilation check
    # -----------------------------------------------------------------------
    successful_files = [f for f in generated_files if f.get("status") == "SUCCESS"]

    if successful_files:
        # max_fix_rounds bounds re-validation: after each round of fixes, we
        # re-run BOTH checks against the (now patched) files, because a fix
        # for one issue can introduce or reveal another. This closes the gap
        # where the old auto-fix loop was single-shot with no re-verification
        # — it would commit a "fix" and never confirm it actually resolved
        # the problem.
        max_fix_rounds = 2
        fixes_per_round = 4

        for round_num in range(max_fix_rounds + 1):
            files_to_check = [
                f for f in generated_files if f.get("status") in ("SUCCESS", "BUILD_FIX")
            ]

            logger.info(
                "Running build validation",
                round=round_num,
                file_count=len(files_to_check),
            )

            # Deterministic check first — it is grounded in real repo content
            # and catches the exact bugs that have shipped before (bad import
            # paths, wrong export/member names) without any LLM guesswork.
            static_issues = _run_static_ts_check(
                github=github,
                branch=branch,
                generated_files=files_to_check,
            )

            # LLM-based check catches things regex can't (CommonModule
            # missing, integration/rendering wiring, navigation-after-auth).
            llm_issues = _run_build_validation(
                bedrock=bedrock,
                github=github,
                branch=branch,
                generated_files=files_to_check,
                contract_files=contract_files,
            )

            # Merge and de-duplicate by (file, issue) so the same problem
            # reported by both checkers doesn't get "fixed" twice.
            seen: set[tuple[str, str]] = set()
            build_issues: list[dict[str, Any]] = []
            for issue in static_issues + llm_issues:
                key = (issue.get("file", ""), issue.get("issue", ""))
                if key in seen:
                    continue
                seen.add(key)
                build_issues.append(issue)

            if not build_issues:
                logger.info("Build validation clean", round=round_num)
                break

            if round_num == max_fix_rounds:
                logger.warning(
                    "Build validation still has issues after max fix rounds, "
                    "leaving them for the Validation Agent / GitHub Actions to catch",
                    issue_count=len(build_issues),
                    issues=build_issues,
                )
                break

            logger.warning(
                "Build validation found issues, attempting fixes",
                round=round_num,
                issue_count=len(build_issues),
            )

            for issue in build_issues[:fixes_per_round]:
                issue = _redirect_integration_issue_to_parent(issue, contract_files)

                # MISSING_MODULE issues (from the deterministic checker) mean
                # the imported file doesn't exist at all — patching the
                # importer can never fix that; the missing file itself must
                # be created. This is the fix for the SCRUM-10 class of bug,
                # where two prior auto-fix rounds just toggled the import
                # path between two equally-nonexistent files.
                if issue.get("kind") == "MISSING_MODULE":
                    fixed = _attempt_create_missing_module(
                        bedrock=bedrock,
                        github=github,
                        branch=branch,
                        event=event,
                        issue=issue,
                        ticket_id=ticket_id,
                        validation_checklist=validation_checklist,
                    )
                else:
                    fixed = _attempt_build_fix(
                        bedrock=bedrock,
                        github=github,
                        branch=branch,
                        event=event,
                        issue=issue,
                        ticket_id=ticket_id,
                        validation_checklist=validation_checklist,
                    )
                if fixed:
                    generated_files.append(fixed)

    # -----------------------------------------------------------------------
    # MANDATORY PR BUILD GATE (non-negotiable)
    # -----------------------------------------------------------------------
    # A PR may only be created once the repository's real CI build check
    # (the actual `npx ng build --configuration production ...` command,
    # run by GitHub Actions -- not a re-implementation of it in this
    # Lambda, which has no Node.js/Angular toolchain) has reported success
    # for the exact commit being shipped. See _run_ci_build_gate for the
    # full fix -> push -> re-poll cycle and shared/github_client.py's
    # wait_for_ci_build/get_failed_job_log_text for the polling mechanics.
    gate_result = _run_ci_build_gate(
        bedrock=bedrock,
        github=github,
        branch=branch,
        event=event,
        ticket_id=ticket_id,
        contract_files=contract_files,
        validation_checklist=validation_checklist,
        generated_files=generated_files,
        config=config,
    )

    if not gate_result["passed"]:
        logger.error(
            "MANDATORY BUILD GATE FAILED — PR will NOT be created",
            workflow_id=workflow_id,
            reason=gate_result["reason"],
            build_errors=gate_result["buildErrors"],
        )

        table.update_status(
            workflow_id=workflow_id,
            status="BUILD_GATE_FAILED",
            agent="development",
            artifacts={
                "reason": "CI_BUILD_GATE_FAILED",
                "buildGateReport": gate_result,
                "generatedFiles": generated_files,
                "branch": branch,
            },
        )

        event["status"] = "BUILD_GATE_FAILED"
        event["currentAgent"] = "development"
        event["artifacts"] = {
            "reason": "CI_BUILD_GATE_FAILED",
            "buildGateReport": gate_result,
            "generatedFiles": generated_files,
            "branch": branch,
        }
        return event

    generated_files = gate_result["generatedFiles"]

    # -----------------------------------------------------------------------
    # Create Pull Request (build gate passed — PR_READY == true)
    # -----------------------------------------------------------------------
    pr_number = gate_result.get("prNumber")
    pr_url = gate_result.get("prUrl")
    if pr_number and gate_result.get("prIsDraft"):
        # The draft PR opened to let the real CI workflow run is now known
        # to build cleanly at HEAD — promote it to ready-for-review rather
        # than leaving it stuck in draft state.
        github.mark_pull_request_ready(pr_number)

    pr = {"number": pr_number, "url": pr_url} if pr_number else github.ensure_pull_request(
        branch=branch,
        ticket_id=ticket_id,
        workflow_id=workflow_id,
    )

    # Build artifacts
    artifacts = event.get("artifacts", {})
    artifacts.update(
        {
            "repository": f"{config.github_repo_owner}/{config.github_repo_name}",
            "branch": branch,
            "commitSha": last_commit["commit"]["sha"] if last_commit else "",
            "pullRequest": pr["url"],
            "pullRequestNumber": pr["number"],
            "generatedFiles": generated_files,
            "branchSyncConflict": bool(branch_sync_result and branch_sync_result.get("conflict")),
            "ciBuildGate": {
                "passed": True,
                "runUrl": gate_result.get("runUrl"),
                "fixRounds": gate_result.get("fixRounds", 0),
            },
        }
    )

    # If this was a replan attempt, mark recovery as SUCCESS
    recovery_history = event.get("recoveryHistory", [])
    if recovery_history:
        # Update the last entry status to SUCCESS
        recovery_history[-1]["status"] = "SUCCESS"
        artifacts["recoveryHistory"] = recovery_history

    # Store artifact in S3
    s3.upload_json(
        f"artifacts/{workflow_id}-generated-code.json",
        {
            "files": generated_files,
            "branch": branch,
            "pullRequest": pr["url"],
            "contract": contract,
        },
    )

    # Update DynamoDB
    table.update_status(
        workflow_id=workflow_id,
        status="DEVELOPMENT_COMPLETE",
        agent="development",
        artifacts=artifacts,
    )

    # Enrich workflow event
    event["status"] = "DEVELOPMENT_COMPLETE"
    event["currentAgent"] = "development"
    event["artifacts"] = artifacts
    # Always include replanAttempt for Step Functions consistency
    event.setdefault("replanAttempt", 0)

    logger.info(
        "Development complete",
        workflow_id=workflow_id,
        files_committed=len(generated_files),
        pr_url=pr["url"],
    )

    return event

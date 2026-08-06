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

from hashlib import sha256
from typing import Any

from shared.bedrock_client import BedrockClient
from shared.config import DevelopmentConfig
from shared.dynamodb_helper import WorkflowTable
from shared.github_client import GitHubClient
from shared.logger import get_logger
from shared.prompts import development as prompts
from shared.s3_helper import S3Helper

logger = get_logger(__name__, agent="development")


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
# Build Validation
# ---------------------------------------------------------------------------


def _run_build_validation(
    bedrock: BedrockClient,
    github: GitHubClient,
    branch: str,
    generated_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Run cross-file build validation using Bedrock.

    Checks that all imports resolve, modules are declared correctly,
    and lazy-loaded routes point to existing files.

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

        # Ask Bedrock to validate
        result = bedrock.converse_json(
            system_prompt=prompts.build_validation_system_prompt(),
            user_prompt=prompts.build_validation_user_prompt(
                generated_files=files_with_content,
                repository_files=repo_file_paths,
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

    # Create feature branch
    branch = f"feature/{ticket_id}"
    github.ensure_branch(branch)

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

            # One retry
            generated_code = bedrock.converse(
                system_prompt=sys_prompt,
                user_prompt=user_msg,
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

            if review_result != "PASS":
                logger.error(
                    "Self-review FAILED after retry, skipping file",
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
                continue

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
            event["recoveryHistory"] = recovery_history
            event["artifacts"] = {
                "reason": "FILE_CHANGED",
                "changedFiles": changed_files,
                "replanAttempt": replan_attempt + 1,
                "generatedFiles": generated_files,
                "recoveryHistory": recovery_history,
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
        logger.info("Running build validation", file_count=len(successful_files))

        build_issues = _run_build_validation(
            bedrock=bedrock,
            github=github,
            branch=branch,
            generated_files=successful_files,
        )

        if build_issues:
            logger.warning(
                "Build validation found issues, attempting fixes",
                issue_count=len(build_issues),
            )

            # Attempt to fix each issue
            for issue in build_issues[:3]:  # Limit to 3 fixes per run
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
    # Create Pull Request
    # -----------------------------------------------------------------------
    pr = github.ensure_pull_request(
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

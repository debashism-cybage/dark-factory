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
2. Run build verification (clone, apply all changes, build).
   - If build fails, retry code generation with build error context.
   - If build still fails, abort — no commit, no PR.
3. Commit all files to GitHub.
4. Create Pull Request.

Input: Workflow event with 'planning.implementationContract' (from Planning Agent).
Output: Workflow event enriched with 'artifacts' and status.
"""

from hashlib import sha256
from typing import Any

from shared.bedrock_client import BedrockClient
from shared.build_verifier import BuildVerifier
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
# Build verification
# ---------------------------------------------------------------------------


def _run_build_verification(
    config: DevelopmentConfig,
    github: GitHubClient,
    branch: str,
    generated_files: dict[str, str],
) -> dict[str, Any]:
    """
    Clone the repository, apply changes, and run the build.

    Args:
        config: DevelopmentConfig with repo info.
        github: GitHubClient (for token access).
        branch: Feature branch name.
        generated_files: Dict of file_path -> generated content.

    Returns:
        Build result dict: {status, duration, logs}.
    """
    repo_url = f"https://github.com/{config.github_repo_owner}/{config.github_repo_name}.git"

    verifier = BuildVerifier(
        repo_url=repo_url,
        branch=branch,
        token=github.token,
    )

    return verifier.verify(generated_files)


# ---------------------------------------------------------------------------
# Build-fix retry
# ---------------------------------------------------------------------------


def _regenerate_with_build_fix(
    bedrock: BedrockClient,
    event: dict[str, Any],
    file_entries: list[dict[str, Any]],
    generated_files: dict[str, str],
    build_logs: str,
) -> dict[str, str]:
    """
    Regenerate code for files that caused build errors.

    Uses the build error output to guide the LLM fix.

    Args:
        bedrock: Initialized BedrockClient.
        event: Workflow event.
        file_entries: File entries from implementationContract.
        generated_files: Current generated code (path -> content).
        build_logs: Build error output.

    Returns:
        Updated generated_files dict with fixes applied.
    """
    logger.info("Retry started — regenerating code with build error context")

    for file_entry in file_entries:
        file_path = file_entry["path"]
        current_content = generated_files.get(file_path)

        if not current_content:
            continue

        expected_changes = file_entry.get("expectedChanges", [])

        fixed_code = bedrock.converse(
            system_prompt=prompts.build_fix_system_prompt(),
            user_prompt=prompts.build_fix_user_prompt(
                event=event,
                file_path=file_path,
                current_content=current_content,
                build_logs=build_logs,
                expected_changes=expected_changes,
            ),
            max_tokens=8192,
        )

        generated_files[file_path] = fixed_code
        logger.info("File regenerated with build fix", file_path=file_path)

    return generated_files


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

    # ===================================================================
    # Phase 1: Generate code for all files (with self-review)
    # ===================================================================
    generated_files: dict[str, str] = {}
    file_metadata: list[dict[str, Any]] = []
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
        # Step 1: Download (MODIFY) or verify absence (CREATE)
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

            # Step 2: Verify SHA256
            if not _verify_sha256(existing_code, expected_hash):
                logger.error(
                    "SHA256 mismatch — file changed since planning",
                    file_path=file_path,
                    expected_hash=expected_hash,
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

            # One retry for self-review
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
                    "Self-review FAILED after retry, aborting file",
                    file_path=file_path,
                    review_result=review_result,
                )
                file_metadata.append(
                    {
                        "path": file_path,
                        "operation": operation,
                        "status": "REVIEW_FAILED",
                        "reason": review_result,
                    }
                )
                continue

        # Store generated code for build verification
        generated_files[file_path] = generated_code
        file_metadata.append(
            {
                "path": file_path,
                "operation": operation,
                "status": "GENERATED",
                "size": len(generated_code),
                "review": "PASS",
            }
        )

    # ===================================================================
    # Handle abort (SHA256 mismatch, file not found, etc.)
    # ===================================================================
    if aborted:
        logger.error("Implementation aborted", workflow_id=workflow_id, reason=abort_reason)

        table.update_status(
            workflow_id=workflow_id,
            status="DEVELOPMENT_ABORTED",
            agent="development",
            artifacts={"reason": abort_reason, "generatedFiles": file_metadata},
        )

        event["status"] = "DEVELOPMENT_ABORTED"
        event["currentAgent"] = "development"
        event["artifacts"] = {"reason": abort_reason, "generatedFiles": file_metadata}
        return event

    # If no files were generated successfully, abort
    if not generated_files:
        logger.error("No files generated successfully", workflow_id=workflow_id)

        table.update_status(
            workflow_id=workflow_id,
            status="DEVELOPMENT_ABORTED",
            agent="development",
            artifacts={"reason": "NO_FILES_GENERATED", "generatedFiles": file_metadata},
        )

        event["status"] = "DEVELOPMENT_ABORTED"
        event["currentAgent"] = "development"
        event["artifacts"] = {"reason": "NO_FILES_GENERATED", "generatedFiles": file_metadata}
        return event

    # ===================================================================
    # Phase 2: Build verification
    # ===================================================================
    logger.info("Build started", file_count=len(generated_files))

    build_result = _run_build_verification(
        config=config,
        github=github,
        branch=branch,
        generated_files=generated_files,
    )

    build_status = build_result["status"]
    logger.info(
        "Build completed",
        status=build_status,
        duration=build_result.get("duration"),
    )

    # If build failed, retry with build error context
    if build_status == "FAILED":
        logger.warning("Build failed, attempting retry with error context")
        logger.info("Retry started")

        generated_files = _regenerate_with_build_fix(
            bedrock=bedrock,
            event=event,
            file_entries=contract_files,
            generated_files=generated_files,
            build_logs=build_result.get("logs", ""),
        )

        # Run build again
        logger.info("Build started (retry)")
        build_result = _run_build_verification(
            config=config,
            github=github,
            branch=branch,
            generated_files=generated_files,
        )

        build_status = build_result["status"]

        if build_status == "FAILED":
            logger.error(
                "Retry failed — build still broken, aborting",
                logs=build_result.get("logs", "")[:500],
            )

            table.update_status(
                workflow_id=workflow_id,
                status="BUILD_FAILED",
                agent="development",
                artifacts={
                    "reason": "BUILD_FAILED",
                    "buildLogs": build_result.get("logs", "")[:2000],
                    "generatedFiles": file_metadata,
                },
            )

            event["status"] = "BUILD_FAILED"
            event["currentAgent"] = "development"
            event["artifacts"] = {
                "reason": "BUILD_FAILED",
                "buildLogs": build_result.get("logs", "")[:2000],
                "generatedFiles": file_metadata,
            }
            return event

        logger.info("Retry succeeded — build passes")

    elif build_status == "BUILD_NOT_SUPPORTED":
        logger.info("Build not supported for this project type, proceeding")

    # ===================================================================
    # Phase 3: Commit all files to GitHub
    # ===================================================================
    logger.info("Committing files", file_count=len(generated_files))

    last_commit: dict[str, Any] | None = None
    committed_files: list[dict[str, Any]] = []

    for file_entry in contract_files:
        file_path = file_entry["path"]
        operation = file_entry.get("operation", "MODIFY")

        if file_path not in generated_files:
            continue

        commit_msg = f"feat({ticket_id}): {operation.lower()} {file_path}"
        last_commit = github.commit_file(
            branch=branch,
            path=file_path,
            content=generated_files[file_path],
            message=commit_msg,
        )

        committed_files.append(
            {
                "path": file_path,
                "operation": operation,
                "status": "SUCCESS",
                "size": len(generated_files[file_path]),
            }
        )

        logger.info("File committed", file_path=file_path, operation=operation)

    # ===================================================================
    # Phase 4: Create Pull Request
    # ===================================================================
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
            "generatedFiles": committed_files,
            "buildVerification": {
                "status": build_status,
                "duration": build_result.get("duration"),
            },
        }
    )

    # Store artifact in S3
    s3.upload_json(
        f"artifacts/{workflow_id}-generated-code.json",
        {
            "files": committed_files,
            "branch": branch,
            "pullRequest": pr["url"],
            "contract": contract,
            "buildVerification": build_result,
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

    logger.info(
        "Development complete",
        workflow_id=workflow_id,
        files_committed=len(committed_files),
        build_status=build_status,
        pr_url=pr["url"],
    )

    return event

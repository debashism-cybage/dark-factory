"""
Validation Agent Lambda Handler.

Reviews generated code — including actual file content and declared parent/
integration files pulled fresh from the PR branch when GitHub access is
configured — and produces a validation report stored in S3.

Input: Workflow event with 'artifacts' (from Development Agent).
Output: Workflow event enriched with validation report and status 'VALIDATION_COMPLETE'.

TODO: Future enhancements: run linters, security scanners, unit tests.
"""

from typing import Any

from shared.bedrock_client import BedrockClient
from shared.config import ValidationConfig
from shared.dynamodb_helper import WorkflowTable
from shared.github_client import GitHubClient
from shared.logger import get_logger
from shared.prompts import validation as prompts
from shared.s3_helper import S3Helper

logger = get_logger(__name__, agent="validation")


def _fetch_code_for_review(
    config: ValidationConfig,
    event: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """
    Fetch generated file content and their declared parent/integration file
    content from the PR branch, so the Validation Agent can actually inspect
    code and confirm integration instead of only reviewing status metadata.

    Applies to every ticket generically — driven entirely by the
    implementationContract's `integratesWith` field, not any special-cased
    ticket logic. Fails open (returns empty dicts) if GitHub isn't configured
    or any fetch fails, so validation still proceeds with metadata-only review.

    Returns:
        Tuple of (generated_file_contents, parent_file_contents), both
        path -> content dicts.
    """
    if not (config.github_secret_name and config.github_repo_owner and config.github_repo_name):
        return {}, {}

    artifacts = event.get("artifacts", {})
    branch = artifacts.get("branch", "")
    generated_files = artifacts.get("generatedFiles", [])
    contract_files = event.get("planning", {}).get("implementationContract", {}).get("files", [])

    if not branch or not generated_files:
        return {}, {}

    try:
        github = GitHubClient(
            owner=config.github_repo_owner,
            repo=config.github_repo_name,
            secret_name=config.github_secret_name,
        )
    except Exception as ex:
        logger.warning("Could not initialize GitHub client for validation", error=str(ex))
        return {}, {}

    generated_contents: dict[str, str] = {}
    for f in generated_files:
        path = f.get("path", "")
        if not path or f.get("status") not in ("SUCCESS", None):
            continue
        try:
            generated_contents[path] = github.get_file_content(path, branch)
        except Exception as ex:
            logger.warning("Could not fetch generated file for review", path=path, error=str(ex))

    parent_paths: set[str] = set()
    generated_paths = set(generated_contents.keys())
    for entry in contract_files:
        if entry.get("operation") != "CREATE":
            continue
        if entry.get("path") not in generated_paths:
            continue
        for parent_path in entry.get("integratesWith", []) or []:
            parent_paths.add(parent_path)

    parent_contents: dict[str, str] = {}
    for path in parent_paths:
        try:
            parent_contents[path] = github.get_file_content(path, branch)
        except Exception as ex:
            logger.warning("Could not fetch parent file for review", path=path, error=str(ex))

    return generated_contents, parent_contents


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Validation agent entry point."""
    logger.info("Validation agent started", workflow_id=event.get("workflowId"))

    config = ValidationConfig()
    workflow_id = event["workflowId"]

    # Initialize services
    s3 = S3Helper(config.bucket_name)
    table = WorkflowTable(config.table_name)

    # Perform AI-powered validation
    try:
        bedrock = BedrockClient(model_id=config.bedrock_model_id)

        generated_contents, parent_contents = _fetch_code_for_review(config, event)

        validation_report = bedrock.converse_json(
            system_prompt=prompts.system_prompt(),
            user_prompt=prompts.user_prompt(
                event,
                generated_file_contents=generated_contents or None,
                parent_file_contents=parent_contents or None,
            ),
            max_tokens=4096,
        )

        logger.info(
            "Validation completed",
            workflow_id=workflow_id,
            overall_status=validation_report.get("overallStatus"),
        )

    except Exception as ex:
        logger.error("AI validation failed, producing basic report", error=str(ex))

        # Fallback: basic report (still passes to not block pipeline)
        validation_report = {
            "overallStatus": "NEEDS_REVIEW",
            "codeReview": {
                "status": "NEEDS_REVIEW",
                "issues": [],
                "suggestions": ["Manual review recommended — AI validation unavailable"],
            },
            "securityReview": {
                "status": "NEEDS_REVIEW",
                "critical": 0,
                "high": 0,
                "medium": 0,
                "findings": [],
            },
            "testCoverage": {
                "status": "NEEDS_REVIEW",
                "estimatedCoverage": "Unknown",
                "missingTests": [],
            },
            "planAlignment": {
                "status": "NEEDS_REVIEW",
                "missingFiles": [],
                "extraFiles": [],
                "notes": f"Validation error: {str(ex)}",
            },
        }

    # Store report in S3
    report_key = f"reports/{workflow_id}-validation.json"
    s3.upload_json(report_key, validation_report)

    # Update DynamoDB
    artifacts = event.get("artifacts", {})
    artifacts["validationReport"] = report_key

    table.update_status(
        workflow_id=workflow_id,
        status="VALIDATION_COMPLETE",
        agent="validation",
        artifacts=artifacts,
    )

    # Enrich workflow event
    event["status"] = "VALIDATION_COMPLETE"
    event["currentAgent"] = "validation"
    event["artifacts"] = artifacts

    return event

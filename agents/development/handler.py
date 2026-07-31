"""
Development Agent Lambda Handler.

Generates source code file-by-file via Bedrock based on the planning output,
commits each file to a feature branch on GitHub, and creates a Pull Request.

Input: Workflow event with 'planning' (from Planning Agent).
Output: Workflow event enriched with 'artifacts' and status 'DEVELOPMENT_COMPLETE'.
"""

from typing import Any

from shared.bedrock_client import BedrockClient
from shared.config import DevelopmentConfig
from shared.dynamodb_helper import WorkflowTable
from shared.github_client import GitHubClient
from shared.logger import get_logger
from shared.prompts import development as prompts
from shared.s3_helper import S3Helper

logger = get_logger(__name__, agent="development")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Development agent entry point."""
    logger.info("Development agent started", workflow_id=event.get("workflowId"))

    config = DevelopmentConfig()

    workflow_id = event["workflowId"]
    ticket_id = event["ticketId"]
    planning = event["planning"]

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

    # Generate and commit each file
    generated_files: list[dict[str, Any]] = []
    last_commit: dict[str, Any] | None = None

    files_to_generate = planning.get("filesToGenerate", [])
    logger.info(
        "Generating files",
        workflow_id=workflow_id,
        file_count=len(files_to_generate),
    )

    for file_path in files_to_generate:
        logger.info("Generating file", file_path=file_path)

        code = bedrock.converse(
            system_prompt=prompts.system_prompt(),
            user_prompt=prompts.user_prompt(event, file_path),
            max_tokens=8192,
        )

        last_commit = github.commit_file(
            branch=branch,
            path=file_path,
            content=code,
            message=f"feat({ticket_id}): generate {file_path}",
        )

        generated_files.append({
            "path": file_path,
            "size": len(code),
        })

    # Create or reuse Pull Request
    pr = github.ensure_pull_request(
        branch=branch,
        ticket_id=ticket_id,
        workflow_id=workflow_id,
    )

    # Build artifacts summary
    artifacts = event.get("artifacts", {})
    artifacts.update({
        "repository": f"{config.github_repo_owner}/{config.github_repo_name}",
        "branch": branch,
        "commitSha": last_commit["commit"]["sha"] if last_commit else "",
        "pullRequest": pr["url"],
        "pullRequestNumber": pr["number"],
        "generatedFiles": generated_files,
    })

    # Store code generation artifact in S3
    s3.upload_json(f"artifacts/{workflow_id}-generated-code.json", {
        "files": generated_files,
        "branch": branch,
        "pullRequest": pr["url"],
    })

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
        files_generated=len(generated_files),
        pr_url=pr["url"],
    )

    return event

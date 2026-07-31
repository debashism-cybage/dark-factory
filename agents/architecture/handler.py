"""
Architecture Agent Lambda Handler.

This agent runs occasionally (on-demand or scheduled) to generate
long-lived project knowledge by analyzing a GitHub repository.

It produces architectural documents stored in S3 that are later
consumed by the Planning Agent to inform ticket-specific plans.

Input: Triggered manually or on schedule (no workflow event required).
       Can optionally receive {"owner": "...", "repo": "...", "branch": "..."}.

Output:
    {
        "status": "SUCCESS" | "FAILED",
        "repository": "owner/repo",
        "documents": ["project.md", "architecture.md", ...]
    }
"""

from typing import Any

from shared.bedrock_client import BedrockClient
from shared.config import ArchitectureConfig
from shared.documents import build_architecture_documents
from shared.github_client import GitHubClient
from shared.logger import get_logger
from shared.prompts import architecture as prompts
from shared.s3_helper import S3Helper

logger = get_logger(__name__, agent="architecture")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Architecture agent entry point."""
    logger.info("Architecture agent started", event=event)

    try:
        config = ArchitectureConfig()

        # Allow override of owner/repo/branch from event (useful for multi-repo)
        owner = event.get("owner", config.github_repo_owner)
        repo = event.get("repo", config.github_repo_name)
        branch = event.get("branch", config.default_branch)

        # Initialize clients
        github = GitHubClient(
            owner=owner,
            repo=repo,
            secret_name=config.github_secret_name,
            default_branch=branch,
        )
        s3 = S3Helper(config.bucket_name)
        bedrock = BedrockClient(config.bedrock_model_id)

        # Gather repository information
        logger.info("Reading repository", owner=owner, repo=repo, branch=branch)
        repository_summary = github.get_repository_summary()
        repository_tree = github.get_repository_tree()
        project_context = github.get_project_context()

        logger.info(
            "Repository analyzed",
            total_files=repository_summary["totalFiles"],
            total_directories=repository_summary["totalDirectories"],
        )

        # Generate architecture via Bedrock
        logger.info("Generating architecture knowledge")
        architecture = bedrock.converse_json(
            system_prompt=prompts.system_prompt(),
            user_prompt=prompts.user_prompt(
                repository_summary=repository_summary,
                repository_tree=repository_tree,
                project_context=project_context,
            ),
            max_tokens=8192,
        )

        # Build markdown documents from raw architecture JSON
        documents = build_architecture_documents(architecture)

        # Upload to S3
        logger.info("Uploading architecture documents to S3")
        s3.upload_architecture_documents(documents)

        # Also store the raw JSON for programmatic access by planning agent
        s3.upload_json("architecture/knowledge.json", architecture)

        logger.info("Architecture generation completed successfully")

        return {
            "status": "SUCCESS",
            "repository": f"{owner}/{repo}",
            "branch": branch,
            "documents": list(documents.keys()),
        }

    except Exception as ex:
        logger.error("Architecture agent failed", error=str(ex), exc_info=True)
        return {
            "status": "FAILED",
            "error": str(ex),
        }

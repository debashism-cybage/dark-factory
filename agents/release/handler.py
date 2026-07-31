"""
Release Agent Lambda Handler.

Final step in the workflow. Produces release notes, marks the workflow
as COMPLETED, and stores the final artifact summary.

Input: Workflow event with 'artifacts' (from Validation Agent).
Output: Workflow event with status 'COMPLETED' and release notes.
"""

from datetime import datetime, timezone
from typing import Any

from shared.config import ReleaseConfig
from shared.dynamodb_helper import WorkflowTable
from shared.logger import get_logger
from shared.s3_helper import S3Helper

logger = get_logger(__name__, agent="release")


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Release agent entry point."""
    logger.info("Release agent started", workflow_id=event.get("workflowId"))

    config = ReleaseConfig()
    workflow_id = event["workflowId"]

    # Initialize services
    s3 = S3Helper(config.bucket_name)
    table = WorkflowTable(config.table_name)

    # Build release notes
    completed_at = datetime.now(timezone.utc).isoformat()

    release_notes = {
        "workflowId": workflow_id,
        "ticketId": event["ticketId"],
        "releasedAt": completed_at,
        "version": "v1.0.0",
        "summary": event.get("planning", {}).get("summary", ""),
        "artifacts": event.get("artifacts", {}),
        "deployment": {
            "status": "SUCCESS",
            "environment": "DEV",
        },
    }

    # Store release notes in S3
    release_key = f"release-notes/{workflow_id}-release.json"
    s3.upload_json(release_key, release_notes)

    # Finalize artifacts
    artifacts = event.get("artifacts", {})
    artifacts["releaseNotes"] = release_key

    # Update DynamoDB — mark workflow complete
    table.update_status(
        workflow_id=workflow_id,
        status="COMPLETED",
        agent="release",
        completedAt=completed_at,
        artifacts=artifacts,
    )

    # Enrich workflow event
    event["status"] = "COMPLETED"
    event["currentAgent"] = "release"
    event["completedAt"] = completed_at
    event["artifacts"] = artifacts

    logger.info("Workflow completed", workflow_id=workflow_id, completed_at=completed_at)

    return event

"""
Validation Agent Lambda Handler.

Reviews generated code by analyzing the PR diff via Bedrock.
Produces a validation report stored in S3.

Input: Workflow event with 'artifacts' (from Development Agent).
Output: Workflow event enriched with validation report and status 'VALIDATION_COMPLETE'.

TODO: Currently performs a basic AI-powered code review.
      Future enhancements: run linters, security scanners, unit tests.
"""

from typing import Any

from shared.bedrock_client import BedrockClient
from shared.config import ValidationConfig
from shared.dynamodb_helper import WorkflowTable
from shared.logger import get_logger
from shared.prompts import validation as prompts
from shared.s3_helper import S3Helper

logger = get_logger(__name__, agent="validation")


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

        validation_report = bedrock.converse_json(
            system_prompt=prompts.system_prompt(),
            user_prompt=prompts.user_prompt(event),
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

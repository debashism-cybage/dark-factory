"""
Workflow Starter Lambda Handler.

API Gateway entrypoint that receives Jira webhook / manual trigger,
validates the payload, and starts the Step Functions state machine.

Input: API Gateway event (or direct invocation) with ticket information.
Output: HTTP response with workflowId and executionArn.
"""

import json
import uuid
from typing import Any

import boto3

from shared.config import WorkflowStarterConfig
from shared.logger import get_logger

logger = get_logger(__name__, agent="workflow-starter")


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the request body from API Gateway or direct invocation."""
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            return json.loads(body, strict=False)
        return body
    return event


def _api_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build a standard API Gateway response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Workflow starter entry point."""
    logger.info("Workflow starter invoked")

    config = WorkflowStarterConfig()

    # Parse incoming request
    body = _parse_body(event)

    ticket_id = body.get("ticketId")
    if not ticket_id:
        logger.warning("Request missing ticketId")
        return _api_response(400, {"message": "ticketId is required"})

    # Build workflow payload
    workflow_id = f"WF-{uuid.uuid4().hex[:8].upper()}"

    workflow = {
        "workflowId": workflow_id,
        "ticketId": ticket_id,
        "summary": body.get("summary", ""),
        "description": body.get("description", ""),
        "priority": body.get("priority", ""),
        "issueType": body.get("issueType", ""),
        "project": body.get("project", ""),
        "assignee": body.get("assignee", ""),
        "status": "STARTED",
    }

    # Start Step Functions execution
    sfn = boto3.client("stepfunctions")

    response = sfn.start_execution(
        stateMachineArn=config.state_machine_arn,
        name=workflow_id,
        input=json.dumps(workflow),
    )

    execution_arn = response["executionArn"]

    logger.info(
        "Workflow started",
        workflow_id=workflow_id,
        ticket_id=ticket_id,
        execution_arn=execution_arn,
    )

    return _api_response(
        200,
        {
            "message": "Workflow started",
            "workflowId": workflow_id,
            "executionArn": execution_arn,
        },
    )

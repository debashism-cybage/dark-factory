"""
Architecture Trigger Lambda Handler.

API Gateway entrypoint that lets the dashboard kick off an on-demand
regeneration of the architecture knowledge base. It fires an asynchronous
(Event) invocation of the Architecture Agent Lambda and returns immediately
-- the agent itself runs for up to 15 minutes, so callers should not wait
on it and should instead poll GET /dashboard for the updated
architecture.lastUpdated timestamp.

Input: API Gateway event (or direct invocation). Body is optional and may
       contain {"owner": "...", "repo": "...", "branch": "..."} to override
       the repository the agent analyzes.
Output: HTTP response acknowledging the trigger was accepted.
"""

import json
from typing import Any

import boto3

from shared.config import ArchitectureTriggerConfig
from shared.logger import get_logger

logger = get_logger(__name__, agent="architecture-trigger")


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Extract the (optional) request body from API Gateway or direct invocation."""
    body = event.get("body", event)
    if isinstance(body, str):
        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return body if isinstance(body, dict) else {}


def _api_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build a standard API Gateway response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Architecture trigger entry point."""
    logger.info("Architecture trigger invoked")

    try:
        config = ArchitectureTriggerConfig()
        payload = _parse_body(event)

        lambda_client = boto3.client("lambda")
        lambda_client.invoke(
            FunctionName=config.architecture_function_name,
            InvocationType="Event",  # fire-and-forget; agent can take up to 15 min
            Payload=json.dumps(payload).encode("utf-8"),
        )

        logger.info(
            "Architecture agent invocation dispatched",
            function_name=config.architecture_function_name,
        )

        return _api_response(
            202,
            {
                "message": "Architecture agent run started",
                "status": "STARTED",
            },
        )

    except Exception as ex:
        logger.error("Architecture trigger failed", error=str(ex), exc_info=True)
        return _api_response(500, {"message": "Failed to start architecture agent"})

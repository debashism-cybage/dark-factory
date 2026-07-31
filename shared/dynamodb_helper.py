"""
DynamoDB helper for workflow state management.

Centralizes the workflow status update pattern used by all agents.
Handles Decimal serialization required by DynamoDB.

Usage:
    from shared.dynamodb_helper import WorkflowTable

    table = WorkflowTable(table_name="dark-factory-workflows")
    table.update_status(workflow_id="WF-123", status="PLANNED", planning={...})
"""

import json
from decimal import Decimal
from typing import Any, Optional

import boto3

from shared.logger import get_logger

logger = get_logger(__name__)


def _serialize_for_dynamodb(data: Any) -> Any:
    """
    Convert floats to Decimals for DynamoDB compatibility.

    DynamoDB does not accept Python floats. This recursively converts
    all float values in a structure to Decimal.
    """
    return json.loads(json.dumps(data, default=str), parse_float=Decimal)


class WorkflowTable:
    """DynamoDB operations for the workflow tracking table."""

    def __init__(self, table_name: str) -> None:
        dynamodb = boto3.resource("dynamodb")
        self.table = dynamodb.Table(table_name)
        self.table_name = table_name
        logger.info("WorkflowTable initialized", table=table_name)

    def update_status(
        self,
        workflow_id: str,
        status: str,
        agent: Optional[str] = None,
        **extra_attributes: Any,
    ) -> None:
        """
        Update workflow status and optional attributes.

        Args:
            workflow_id: The workflow identifier (partition key).
            status: New status value (e.g., PLANNED, DEVELOPMENT_COMPLETE).
            agent: Current agent name (optional).
            **extra_attributes: Additional attributes to set on the item.
        """
        # Build the update expression dynamically
        expr_names: dict[str, str] = {"#status": "status"}
        expr_values: dict[str, Any] = {":status": status}
        set_parts: list[str] = ["#status = :status"]

        if agent:
            set_parts.append("currentAgent = :agent")
            expr_values[":agent"] = agent

        for key, value in extra_attributes.items():
            placeholder = f":{key}"
            set_parts.append(f"{key} = {placeholder}")
            expr_values[placeholder] = _serialize_for_dynamodb(value)

        update_expression = "SET " + ", ".join(set_parts)

        self.table.update_item(
            Key={"WorkflowId": workflow_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

        logger.info(
            "Workflow status updated",
            workflow_id=workflow_id,
            status=status,
            agent=agent,
        )

    def get_workflow(self, workflow_id: str) -> Optional[dict[str, Any]]:
        """
        Get a workflow item by ID.

        Args:
            workflow_id: The workflow identifier.

        Returns:
            The workflow item dict, or None if not found.
        """
        response = self.table.get_item(Key={"WorkflowId": workflow_id})
        return response.get("Item")

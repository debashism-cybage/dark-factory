"""
Dashboard service.

Reads the latest Step Functions execution and returns
dashboard data for the React Control Tower.
"""

from __future__ import annotations

from datetime import datetime, timezone

import boto3

from shared.config import DashboardApiConfig
from shared.logger import get_logger

logger = get_logger(__name__, agent="dashboard-api")


class DashboardService:
    """Dashboard aggregation service."""

    def __init__(self) -> None:
        self.config = DashboardApiConfig()
        self.sfn = boto3.client("stepfunctions")

    def get_dashboard(self) -> dict:
        """
        Return dashboard payload.
        """

        executions = self.sfn.list_executions(
            stateMachineArn=self.config.state_machine_arn,
            maxResults=1,
        )

        if not executions["executions"]:
            return {
                "hero": None,
                "pipeline": [],
                "summary": {},
                "quality": {},
                "activity": [],
                "history": [],
            }

        execution = executions["executions"][0]

        execution_details = self.sfn.describe_execution(
            executionArn=execution["executionArn"]
        )

        workflow = execution_details["input"]

        import json

        workflow = json.loads(workflow)

        progress = self._calculate_progress(execution["status"])

        return {
            "hero": {
                "workflowId": workflow.get("workflowId"),
                "ticketId": workflow.get("ticketId"),
                "title": workflow.get("summary"),
                "status": execution["status"],
                "currentStage": self._current_stage(execution["status"]),
                "progress": progress,
                "confidence": 98,
                "startedAt": execution["startDate"].isoformat(),
                "eta": "~1m",
            },
            "pipeline": [],
            "summary": {},
            "quality": {},
            "activity": [],
            "history": [],
        }

    def _calculate_progress(self, status: str) -> int:
        if status == "RUNNING":
            return 65

        if status == "SUCCEEDED":
            return 100

        if status == "FAILED":
            return 100

        return 0

    def _current_stage(self, status: str) -> str:
        if status == "RUNNING":
            return "Validation"

        if status == "SUCCEEDED":
            return "Release"

        return "Planning"
"""
Typed model for the workflow event passed through Step Functions.

This is the single source of truth for the data contract between
the workflow starter and all downstream agents.

Usage:
    from shared.models.workflow import WorkflowEvent

    # Parse from Step Functions input
    workflow = WorkflowEvent.from_dict(event)

    # Access typed fields
    print(workflow.workflow_id, workflow.ticket_id)

    # Convert back to dict for Step Functions output
    return workflow.to_dict()
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowEvent:
    """
    Represents the event payload flowing through Step Functions.

    This is the contract between workflow-starter and all agents.
    Agents enrich this event with their outputs before passing it downstream.
    """

    workflow_id: str
    ticket_id: str
    summary: str = ""
    description: str = ""
    priority: str = ""
    issue_type: str = ""
    project: str = ""
    assignee: str = ""
    status: str = "STARTED"

    # Populated by planning agent
    planning: dict[str, Any] = field(default_factory=dict)

    # Populated by development agent
    artifacts: dict[str, Any] = field(default_factory=dict)

    # Populated by each agent
    current_agent: str = ""

    # Populated by release agent
    completed_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowEvent":
        """
        Parse a WorkflowEvent from a Step Functions payload dict.

        Unknown keys are silently ignored so this remains forward-compatible
        as new fields are added.
        """
        return cls(
            workflow_id=data.get("workflowId", ""),
            ticket_id=data.get("ticketId", ""),
            summary=data.get("summary", ""),
            description=data.get("description", ""),
            priority=data.get("priority", ""),
            issue_type=data.get("issueType", ""),
            project=data.get("project", ""),
            assignee=data.get("assignee", ""),
            status=data.get("status", "STARTED"),
            planning=data.get("planning", {}),
            artifacts=data.get("artifacts", {}),
            current_agent=data.get("currentAgent", ""),
            completed_at=data.get("completedAt", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize back to the Step Functions payload format.

        Uses camelCase keys to match the existing contract.
        """
        result: dict[str, Any] = {
            "workflowId": self.workflow_id,
            "ticketId": self.ticket_id,
            "summary": self.summary,
            "description": self.description,
            "priority": self.priority,
            "issueType": self.issue_type,
            "project": self.project,
            "assignee": self.assignee,
            "status": self.status,
        }

        if self.planning:
            result["planning"] = self.planning

        if self.artifacts:
            result["artifacts"] = self.artifacts

        if self.current_agent:
            result["currentAgent"] = self.current_agent

        if self.completed_at:
            result["completedAt"] = self.completed_at

        return result

    def validate(self) -> None:
        """
        Validate required fields.

        Raises:
            ValueError: If workflow_id or ticket_id is missing.
        """
        if not self.workflow_id:
            raise ValueError("workflow_id is required")
        if not self.ticket_id:
            raise ValueError("ticket_id is required")

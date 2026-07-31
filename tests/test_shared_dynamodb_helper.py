"""Tests for shared.dynamodb_helper module."""

import boto3
import pytest
from moto import mock_aws

from shared.dynamodb_helper import WorkflowTable


TABLE_NAME = "test-workflows"


@pytest.fixture
def workflow_table():
    """Create WorkflowTable with mocked DynamoDB."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "WorkflowId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "WorkflowId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )

        table = WorkflowTable(TABLE_NAME)
        yield table


class TestWorkflowTable:

    def test_update_status_basic(self, workflow_table):
        workflow_table.update_status(
            workflow_id="WF-001",
            status="PLANNED",
        )

        item = workflow_table.get_workflow("WF-001")
        assert item is not None
        assert item["status"] == "PLANNED"

    def test_update_status_with_agent(self, workflow_table):
        workflow_table.update_status(
            workflow_id="WF-002",
            status="DEVELOPMENT_COMPLETE",
            agent="development",
        )

        item = workflow_table.get_workflow("WF-002")
        assert item["status"] == "DEVELOPMENT_COMPLETE"
        assert item["currentAgent"] == "development"

    def test_update_status_with_extra_attributes(self, workflow_table):
        artifacts = {"branch": "feature/TEST-1", "pr": "https://github.com/pr/1"}

        workflow_table.update_status(
            workflow_id="WF-003",
            status="COMPLETED",
            agent="release",
            artifacts=artifacts,
            completedAt="2025-01-01T00:00:00Z",
        )

        item = workflow_table.get_workflow("WF-003")
        assert item["status"] == "COMPLETED"
        assert item["artifacts"]["branch"] == "feature/TEST-1"
        assert item["completedAt"] == "2025-01-01T00:00:00Z"

    def test_get_workflow_not_found(self, workflow_table):
        item = workflow_table.get_workflow("NONEXISTENT")
        assert item is None

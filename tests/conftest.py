"""
Shared test fixtures for Dark Factory.

Uses moto to mock AWS services in tests.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def aws_env_vars(monkeypatch):
    """Set required AWS-related env vars for all tests."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


@pytest.fixture
def workflow_event():
    """Sample workflow event for testing."""
    return {
        "workflowId": "WF-TEST1234",
        "ticketId": "PROJ-100",
        "summary": "Add user authentication",
        "description": "Implement JWT-based authentication for the API",
        "priority": "High",
        "issueType": "Story",
        "project": "dark-factory",
        "assignee": "developer@example.com",
        "status": "STARTED",
    }

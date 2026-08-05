"""
Dashboard API Lambda.

Provides a single endpoint for the React Control Tower.

Current implementation:
- Returns workflow information from Step Functions.

Future:
- CloudWatch Logs
- GitHub
- Jira
- Quality Metrics
"""

import json
from typing import Any

from dashboard_api.service import DashboardService
from shared.logger import get_logger

logger = get_logger(__name__, agent="dashboard-api")


def _api_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Standard API Gateway response."""

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Dashboard API entry point."""

    logger.info("Dashboard API invoked")

    service = DashboardService()

    dashboard = service.get_dashboard()

    return _api_response(200, dashboard)
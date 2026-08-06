"""
Dashboard API Lambda Handler.

Read-only endpoint that aggregates workflow data for the React frontend.
This Lambda NEVER triggers workflows — it only reads execution state.

Endpoint: GET /dashboard
"""

import json
from datetime import UTC, datetime
from typing import Any

from service import DashboardService

from shared.config import DashboardApiConfig
from shared.logger import get_logger

logger = get_logger(__name__, agent="dashboard-api")

DASHBOARD_VERSION = "1.0"
API_VERSION = "v1"


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Dashboard API entry point."""
    logger.info("Dashboard API invoked")

    try:
        config = DashboardApiConfig()
        service = DashboardService(config.state_machine_arn)

        dashboard = service.get_dashboard()

        # Add API metadata
        dashboard["metadata"] = {
            "generatedAt": datetime.now(UTC).isoformat(),
            "dashboardVersion": DASHBOARD_VERSION,
            "apiVersion": API_VERSION,
        }

        return _response(200, dashboard)

    except Exception as ex:
        logger.error("Dashboard API error", error=str(ex), exc_info=True)
        return _response(
            500,
            {
                "error": "Internal server error",
                "metadata": {
                    "generatedAt": datetime.now(UTC).isoformat(),
                    "dashboardVersion": DASHBOARD_VERSION,
                    "apiVersion": API_VERSION,
                },
            },
        )


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body, default=str),
    }

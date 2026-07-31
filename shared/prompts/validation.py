"""
Prompts for the Validation Agent.

The validation agent reviews AI-generated code and produces
a structured quality report.
"""

import json
from typing import Any


def system_prompt() -> str:
    """System prompt for the validation agent."""
    return (
        "You are a senior code reviewer. "
        "Analyze the generated code artifacts and produce a validation report. "
        "Return only valid JSON. No markdown. No explanations."
    )


def user_prompt(event: dict[str, Any]) -> str:
    """Build the validation review prompt from the workflow event."""
    planning = event.get("planning", {})
    artifacts = event.get("artifacts", {})

    return f"""Review the following AI-generated code delivery.

Validate that:
1. The generated files match the implementation plan.
2. Code quality standards are met.
3. No obvious security issues.
4. Test coverage is adequate.

Implementation Plan Summary:
{planning.get("summary", "N/A")}

Requirements:
{json.dumps(planning.get("requirements", []), indent=2)}

Acceptance Criteria:
{json.dumps(planning.get("acceptanceCriteria", []), indent=2)}

Generated Files:
{json.dumps(artifacts.get("generatedFiles", []), indent=2)}

Branch: {artifacts.get("branch", "N/A")}
Pull Request: {artifacts.get("pullRequest", "N/A")}

Produce EXACTLY this JSON:

{{
    "overallStatus": "PASSED" or "FAILED" or "NEEDS_REVIEW",
    "codeReview": {{
        "status": "PASSED" or "FAILED",
        "issues": [],
        "suggestions": []
    }},
    "securityReview": {{
        "status": "PASSED" or "FAILED",
        "critical": 0,
        "high": 0,
        "medium": 0,
        "findings": []
    }},
    "testCoverage": {{
        "status": "PASSED" or "FAILED",
        "estimatedCoverage": "",
        "missingTests": []
    }},
    "planAlignment": {{
        "status": "PASSED" or "FAILED",
        "missingFiles": [],
        "extraFiles": [],
        "notes": ""
    }}
}}"""

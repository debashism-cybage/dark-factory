"""
Prompts for the Development Agent.

The development agent generates source code file-by-file
based on the planning output.
"""

import json
from typing import Any


def system_prompt() -> str:
    """System prompt for code generation."""
    return (
        "You are an expert software engineer. "
        "Generate complete, production-ready code. "
        "Return ONLY the file contents. "
        "Do not wrap in markdown. Do not use code fences. "
        "Do not explain the code."
    )


def user_prompt(workflow: dict[str, Any], file_path: str) -> str:
    """
    Build the user prompt for code file generation.

    Args:
        workflow: Full workflow state including planning output.
        file_path: The file to generate.
    """
    planning = workflow.get("planning", {})

    return f"""Generate COMPLETE production-ready code for this file.

File to generate: {file_path}

--------------------------------------------------
Project Context
--------------------------------------------------

Summary: {planning.get("summary", "")}

Requirements:
{json.dumps(planning.get("requirements", []), indent=2)}

Acceptance Criteria:
{json.dumps(planning.get("acceptanceCriteria", []), indent=2)}

Implementation Plan:
{json.dumps(planning.get("implementationPlan", []), indent=2)}

Technologies:
{json.dumps(planning.get("technologies", []), indent=2)}

Affected Modules:
{json.dumps(planning.get("affectedModules", []), indent=2)}

--------------------------------------------------

Return ONLY the file contents for: {file_path}
Do not wrap in markdown. Do not use ``` fences. Do not explain."""

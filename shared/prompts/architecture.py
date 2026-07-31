"""
Prompts for the Architecture Agent.

The architecture agent analyzes a GitHub repository and produces
long-lived project knowledge consumed by all other agents.
"""

import json
from typing import Any


def system_prompt() -> str:
    """System prompt for the architecture agent."""
    return (
        "You are a Senior Software Architect. "
        "You analyze repositories and produce structured architectural knowledge. "
        "Return only valid JSON. No markdown. No explanations."
    )


def user_prompt(
    repository_summary: dict[str, Any],
    repository_tree: list[dict[str, Any]],
    project_context: dict[str, Any],
) -> str:
    """Build the user prompt for architecture knowledge generation."""
    return f"""Analyze this GitHub repository and generate long-term architectural knowledge.

This knowledge will be consumed by Planning, Development, Validation and Release agents.

DO NOT write code.
DO NOT generate implementation plans.
Only analyze the project structure and architecture.

--------------------------------------------------
Repository Summary
--------------------------------------------------

{json.dumps(repository_summary, indent=2)}

--------------------------------------------------
Repository Structure
--------------------------------------------------

{json.dumps(repository_tree, indent=2)}

--------------------------------------------------
Important Files
--------------------------------------------------

{json.dumps(project_context, indent=2)}

--------------------------------------------------

Generate EXACTLY this JSON structure:

{{
    "project": {{
        "name": "",
        "description": "",
        "businessPurpose": "",
        "technologyStack": [],
        "frameworks": [],
        "languages": [],
        "buildTools": [],
        "packageManagers": []
    }},
    "architecture": {{
        "style": "",
        "layers": [],
        "majorModules": [],
        "designPatterns": [],
        "externalDependencies": [],
        "configurationFiles": [],
        "entryPoints": []
    }},
    "repository": {{
        "importantDirectories": [],
        "importantFiles": [],
        "codingConventions": [],
        "namingConventions": [],
        "folderOrganization": ""
    }},
    "standards": {{
        "codingStandards": [],
        "testingStandards": [],
        "securityStandards": [],
        "documentationStandards": [],
        "deploymentStandards": []
    }},
    "metadata": {{
        "repositoryType": "",
        "primaryLanguage": "",
        "framework": "",
        "generatedBy": "Architecture Agent",
        "version": "1.0"
    }}
}}

Return ONLY valid JSON. No markdown. No explanations. No additional text."""

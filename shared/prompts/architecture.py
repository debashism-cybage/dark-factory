"""
Prompts for the Architecture Agent.

The architecture agent analyzes a GitHub repository and produces
long-lived project knowledge consumed by all other agents.
"""

import json
from typing import Any


def system_prompt() -> str:
    return (
        "You are an expert Software Architect and AI Knowledge Engineer. "
        "Your task is to extract durable architectural knowledge from software repositories. "
        "Never invent information. "
        "Only infer conclusions supported by repository evidence. "
        "If something cannot be determined, return 'Not detected from repository.'. "
        "Return ONLY valid JSON matching the requested schema."
    )


def user_prompt(
    repository_summary: dict[str, Any],
    repository_tree: list[dict[str, Any]],
    project_context: dict[str, Any],
) -> str:
    """Build the user prompt for architecture knowledge generation."""
    return f"""Analyze this GitHub repository and build a long-lived architectural knowledge base.

This knowledge will be consumed by Planning, Development, Validation and Release agents.

Your goal is NOT to summarize the repository.

Your goal is to extract durable architectural knowledge.

Only describe what is supported by repository evidence.

Never invent functionality.

Never assume implementation details.

If information cannot be determined, explicitly return:

"Not detected from repository."

Focus on:

- Project purpose
- Technology stack
- Architecture style
- Layer responsibilities
- Major modules
- Module responsibilities
- Repository organization
- Coding conventions
- Naming conventions
- Configuration strategy
- Dependency management
- External integrations
- Entry points
- Build process
- Testing approach
- Security practices
- Architectural constraints

Provide information that another AI agent could use without re-analyzing the repository.

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
        "styleReason": "",
        "layers": [],
        "layerResponsibilities": [],
        "majorModules": [],
        "moduleResponsibilities": [],
        "designPatterns": [],
        "dependencyFlow": [],
        "externalDependencies": [],
        "configurationFiles": [],
        "entryPoints": [],
        "authentication": "",
        "routing": "",
        "stateManagement": "",
        "externalServices": [],
        "buildProcess": "",
        "architecturalConstraints": [],
        "technicalRisks": []
    }},
    "repository": {{
        "importantDirectories": [],
        "importantFiles": [],
        "directoryDescriptions": [],
        "codingConventions": [],
        "namingConventions": [],
        "folderOrganization": "",
        "extensionPoints": [],
        "recommendedLocations": {{}}
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

"""
Document builders for architecture knowledge output.

Converts raw architecture JSON into markdown documents
suitable for storage in S3.
"""

from typing import Any


def build_architecture_documents(architecture: dict[str, Any]) -> dict[str, Any]:
    """
    Convert raw architecture JSON into markdown documents + metadata.

    Args:
        architecture: The raw JSON from the architecture agent's Bedrock response.

    Returns:
        Dict of filename -> content (str for markdown, dict for JSON files).
    """
    project = architecture.get("project", {})
    arch = architecture.get("architecture", {})
    repository = architecture.get("repository", {})
    standards = architecture.get("standards", {})
    metadata = architecture.get("metadata", {})

    def _bullet(values: list) -> str:
        if not values:
            return "- None"
        return "\n".join(f"- {item}" for item in values)

    documents = {
        "project.md": f"""# Project

## Name
{project.get("name", "")}

## Description
{project.get("description", "")}

## Business Purpose
{project.get("businessPurpose", "")}

## Technology Stack
{_bullet(project.get("technologyStack", []))}

## Frameworks
{_bullet(project.get("frameworks", []))}

## Languages
{_bullet(project.get("languages", []))}

## Build Tools
{_bullet(project.get("buildTools", []))}

## Package Managers
{_bullet(project.get("packageManagers", []))}
""",
        "architecture.md": f"""# Architecture

## Style
{arch.get("style", "")}

## Layers
{_bullet(arch.get("layers", []))}

## Major Modules
{_bullet(arch.get("majorModules", []))}

## Design Patterns
{_bullet(arch.get("designPatterns", []))}

## External Dependencies
{_bullet(arch.get("externalDependencies", []))}

## Configuration Files
{_bullet(arch.get("configurationFiles", []))}

## Entry Points
{_bullet(arch.get("entryPoints", []))}
""",
        "repository.md": f"""# Repository

## Important Directories
{_bullet(repository.get("importantDirectories", []))}

## Important Files
{_bullet(repository.get("importantFiles", []))}

## Coding Conventions
{_bullet(repository.get("codingConventions", []))}

## Naming Conventions
{_bullet(repository.get("namingConventions", []))}

## Folder Organization
{repository.get("folderOrganization", "")}
""",
        "standards.md": f"""# Standards

## Coding Standards
{_bullet(standards.get("codingStandards", []))}

## Testing Standards
{_bullet(standards.get("testingStandards", []))}

## Security Standards
{_bullet(standards.get("securityStandards", []))}

## Documentation Standards
{_bullet(standards.get("documentationStandards", []))}

## Deployment Standards
{_bullet(standards.get("deploymentStandards", []))}
""",
        "metadata.json": metadata,
    }

    return documents

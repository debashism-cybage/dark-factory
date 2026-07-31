import json
import logging

import boto3

from prompt_builder import build_architecture_prompt

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class BedrockClient:

    def __init__(self, model_id):

        self.model_id = model_id

        self.client = boto3.client(
            "bedrock-runtime"
        )

    def generate_architecture(
        self,
        repository_summary,
        repository_tree,
        project_context
    ):

        prompt = build_architecture_prompt(
            repository_summary,
            repository_tree,
            project_context
        )

        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ]
        }

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body)
        )

        payload = json.loads(
            response["body"].read()
        )

        text = payload["output"]["message"]["content"][0]["text"]

        logger.info("Architecture generated successfully.")

        architecture = json.loads(text)

        return {
            "documents": self._build_documents(architecture),
            "raw": architecture
        }

    def _build_documents(self, architecture):

        project = architecture["project"]
        arch = architecture["architecture"]
        repository = architecture["repository"]
        standards = architecture["standards"]
        metadata = architecture["metadata"]

        documents = {
            "project.md": self._project_md(project),
            "architecture.md": self._architecture_md(arch),
            "repository.md": self._repository_md(repository),
            "standards.md": self._standards_md(standards),
            "metadata.json": metadata
        }

        return documents

    def _project_md(self, project):

        return f"""# Project

## Name
{project.get("name","")}

## Description
{project.get("description","")}

## Business Purpose
{project.get("businessPurpose","")}

## Technology Stack
{self._bullet(project.get("technologyStack", []))}

## Frameworks
{self._bullet(project.get("frameworks", []))}

## Languages
{self._bullet(project.get("languages", []))}

## Build Tools
{self._bullet(project.get("buildTools", []))}

## Package Managers
{self._bullet(project.get("packageManagers", []))}
"""

    def _architecture_md(self, architecture):

        return f"""# Architecture

## Style
{architecture.get("style","")}

## Layers
{self._bullet(architecture.get("layers", []))}

## Major Modules
{self._bullet(architecture.get("majorModules", []))}

## Design Patterns
{self._bullet(architecture.get("designPatterns", []))}

## External Dependencies
{self._bullet(architecture.get("externalDependencies", []))}

## Configuration Files
{self._bullet(architecture.get("configurationFiles", []))}

## Entry Points
{self._bullet(architecture.get("entryPoints", []))}
"""

    def _repository_md(self, repository):

        return f"""# Repository

## Important Directories
{self._bullet(repository.get("importantDirectories", []))}

## Important Files
{self._bullet(repository.get("importantFiles", []))}

## Coding Conventions
{self._bullet(repository.get("codingConventions", []))}

## Naming Conventions
{self._bullet(repository.get("namingConventions", []))}

## Folder Organization
{repository.get("folderOrganization","")}
"""

    def _standards_md(self, standards):

        return f"""# Standards

## Coding Standards
{self._bullet(standards.get("codingStandards", []))}

## Testing Standards
{self._bullet(standards.get("testingStandards", []))}

## Security Standards
{self._bullet(standards.get("securityStandards", []))}

## Documentation Standards
{self._bullet(standards.get("documentationStandards", []))}

## Deployment Standards
{self._bullet(standards.get("deploymentStandards", []))}
"""

    def _bullet(self, values):

        if not values:
            return "- None"

        return "\n".join(
            f"- {item}"
            for item in values
        )
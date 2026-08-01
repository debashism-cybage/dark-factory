"""
Prompts for the Development Agent.

The development agent generates or modifies source code based on
the planning output, architecture knowledge, and repository context.

It prefers modifying existing files over creating new ones.
"""

import json
from typing import Any


def system_prompt(architecture_knowledge: str = "") -> str:
    """
    System prompt for code generation.

    Args:
        architecture_knowledge: Combined architecture docs (project.md,
            architecture.md, repository.md, standards.md) loaded from S3.
    """
    base = (
        "You are an expert software engineer working on an existing codebase.\n\n"
        "CRITICAL RULES:\n"
        "1. ALWAYS prefer modifying existing files over creating new ones.\n"
        "2. Do NOT create a new component/module/service when one already exists "
        "that can be modified to satisfy the requirement.\n"
        "3. Create new files ONLY when no suitable existing file can be modified.\n"
        "4. Reuse existing project patterns, utilities, and conventions.\n"
        "5. Follow the existing folder structure and naming conventions.\n"
        "6. Return ONLY the complete file contents.\n"
        "7. Do not wrap in markdown. Do not use code fences.\n"
        "8. Do not explain the code.\n"
    )

    if architecture_knowledge:
        base += (
            "\n--------------------------------------------------\n"
            "PROJECT ARCHITECTURE KNOWLEDGE\n"
            "--------------------------------------------------\n\n"
            f"{architecture_knowledge}\n"
        )

    return base


def user_prompt_modify(
    workflow: dict[str, Any],
    file_path: str,
    existing_content: str,
    repository_context: dict[str, Any],
    reason: str = "",
) -> str:
    """
    Build the user prompt for MODIFYING an existing file.

    Args:
        workflow: Full workflow state including planning output.
        file_path: The file to modify.
        existing_content: Current content of the file from the repository.
        repository_context: The RepositoryContext object with candidate files info.
        reason: Explanation of why this file is being modified.
    """
    planning = workflow.get("planning", {})

    return f"""MODIFY the following existing file to implement the requested changes.

Action: MODIFY (update existing file)
File: {file_path}
Reason: {reason}

--------------------------------------------------
EXISTING FILE CONTENT
--------------------------------------------------

{existing_content}

--------------------------------------------------
CHANGE REQUEST
--------------------------------------------------

Summary: {planning.get("summary", "")}

Requirements:
{json.dumps(planning.get("requirements", []), indent=2)}

Acceptance Criteria:
{json.dumps(planning.get("acceptanceCriteria", []), indent=2)}

Implementation Plan:
{json.dumps(planning.get("implementationPlan", []), indent=2)}

--------------------------------------------------
REPOSITORY CONTEXT
--------------------------------------------------

Existing Components: {json.dumps(repository_context.get("existingComponents", []))}
Existing Services: {json.dumps(repository_context.get("existingServices", []))}
Existing Routes: {json.dumps(repository_context.get("existingRoutes", []))}
Existing Models: {json.dumps(repository_context.get("existingModels", []))}
Framework: {repository_context.get("framework", "")}

--------------------------------------------------
INSTRUCTIONS
--------------------------------------------------

1. Modify the existing file to implement the required changes.
2. Preserve all existing functionality that is NOT being changed.
3. Follow the existing code style and patterns in this file.
4. Do NOT rewrite the entire file from scratch — make targeted changes.
5. Return the COMPLETE modified file contents.

Return ONLY the complete file contents for: {file_path}
Do not wrap in markdown. Do not use ``` fences. Do not explain."""


def user_prompt_create(
    workflow: dict[str, Any],
    file_path: str,
    repository_context: dict[str, Any],
    reason: str = "",
) -> str:
    """
    Build the user prompt for CREATING a new file.

    This is used only when no suitable existing file was found.

    Args:
        workflow: Full workflow state including planning output.
        file_path: The file to create.
        repository_context: The RepositoryContext object with candidate files info.
        reason: Explanation of why a new file is needed.
    """
    planning = workflow.get("planning", {})

    return f"""CREATE a new file following the project's existing patterns.

Action: CREATE (new file — no suitable existing file found)
File: {file_path}
Reason: {reason}

--------------------------------------------------
CHANGE REQUEST
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

--------------------------------------------------
REPOSITORY CONTEXT
--------------------------------------------------

Existing Components: {json.dumps(repository_context.get("existingComponents", []))}
Existing Services: {json.dumps(repository_context.get("existingServices", []))}
Existing Routes: {json.dumps(repository_context.get("existingRoutes", []))}
Existing Models: {json.dumps(repository_context.get("existingModels", []))}
Framework: {repository_context.get("framework", "")}
Architecture Summary: {repository_context.get("architectureSummary", "")}

--------------------------------------------------
INSTRUCTIONS
--------------------------------------------------

1. Create the file following existing project patterns and conventions.
2. Follow the project's folder structure and naming conventions.
3. Reuse existing utilities, services, and patterns from the codebase.
4. Ensure the new file integrates cleanly with existing code.
5. Return the COMPLETE file contents.

Return ONLY the complete file contents for: {file_path}
Do not wrap in markdown. Do not use ``` fences. Do not explain."""


# ---------------------------------------------------------------------------
# AI decision step — MODIFY vs CREATE
# ---------------------------------------------------------------------------


def decision_system_prompt() -> str:
    """System prompt for the AI-based MODIFY/CREATE decision step."""
    return (
        "You are a senior software engineer analyzing a Jira ticket to decide "
        "whether existing source files should be modified or new files created.\n\n"
        "RULES:\n"
        "1. ALWAYS prefer MODIFY over CREATE.\n"
        "2. Choose MODIFY if ANY existing file can reasonably be updated to "
        "satisfy the requirement.\n"
        "3. Choose CREATE only when there is absolutely no suitable existing file.\n"
        "4. Return ONLY valid JSON. No markdown, no explanation.\n"
    )


def decision_user_prompt(
    workflow: dict[str, Any],
    repository_context: dict[str, Any],
    architecture_summary: str = "",
) -> str:
    """
    Build the user prompt for the AI decision step.

    The LLM decides which existing files to modify (or whether to create new ones)
    for EACH file in filesToGenerate.

    Args:
        workflow: Full workflow state including planning output.
        repository_context: RepositoryContext with candidate files.
        architecture_summary: Condensed architecture knowledge.

    Returns:
        Prompt string asking for a JSON decision.
    """
    planning = workflow.get("planning", {})

    return f"""Analyze this ticket and decide: should we MODIFY existing files or CREATE new ones?

--------------------------------------------------
TICKET
--------------------------------------------------

Ticket ID: {workflow.get("ticketId", "")}
Summary: {workflow.get("summary", "")}
Description: {workflow.get("description", "")}

--------------------------------------------------
PLANNING OUTPUT
--------------------------------------------------

Summary: {planning.get("summary", "")}
Affected Modules: {json.dumps(planning.get("affectedModules", []))}
Files to Generate: {json.dumps(planning.get("filesToGenerate", []))}
Implementation Plan: {json.dumps(planning.get("implementationPlan", []), indent=2)}

--------------------------------------------------
EXISTING REPOSITORY FILES (candidates)
--------------------------------------------------

{json.dumps(repository_context.get("candidateFiles", []), indent=2)}

Existing Components: {json.dumps(repository_context.get("existingComponents", []))}
Existing Services: {json.dumps(repository_context.get("existingServices", []))}
Existing Routes: {json.dumps(repository_context.get("existingRoutes", []))}
Existing Models: {json.dumps(repository_context.get("existingModels", []))}
Framework: {repository_context.get("framework", "")}

--------------------------------------------------
ARCHITECTURE SUMMARY
--------------------------------------------------

{architecture_summary}

--------------------------------------------------
INSTRUCTIONS
--------------------------------------------------

For EACH file in "Files to Generate", decide:
- MODIFY: if an existing candidate file can be updated to satisfy the requirement.
- CREATE: only if no existing file is suitable.

Return ONLY a JSON array with one decision per file:

[
  {{
    "plannedFile": "<file from filesToGenerate>",
    "action": "MODIFY" or "CREATE",
    "reason": "<brief explanation>",
    "targetFiles": ["<existing file to modify>"] or ["<new file to create>"]
  }}
]

Return ONLY valid JSON. No markdown fences. No explanation outside the JSON."""


# ---------------------------------------------------------------------------
# Backward-compatible legacy prompt (kept for safety)
# ---------------------------------------------------------------------------


def system_prompt_legacy() -> str:
    """Legacy system prompt (no architecture knowledge). Kept for backward compat."""
    return (
        "You are an expert software engineer. "
        "Generate complete, production-ready code. "
        "Return ONLY the file contents. "
        "Do not wrap in markdown. Do not use code fences. "
        "Do not explain the code."
    )


def user_prompt(workflow: dict[str, Any], file_path: str) -> str:
    """
    Legacy user prompt for code file generation (backward compatible).

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

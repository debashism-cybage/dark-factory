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
        "You are a senior code reviewer and QA engineer performing the final gate "
        "before a Jira ticket is considered done.\n"
        "Analyze the generated code artifacts and produce a validation report.\n"
        "Beyond code quality and security, you MUST also check integration: a "
        "component/file that was CREATED but is never imported, declared, or "
        "rendered by any parent is NOT a passing implementation, even if it "
        "compiles cleanly — treat this as a planAlignment failure, not a nitpick.\n"
        "Similarly, for authentication/login changes, code that authenticates but "
        "never triggers navigation to the expected destination is NOT passing.\n"
        "Return only valid JSON. No markdown. No explanations."
    )


def user_prompt(
    event: dict[str, Any],
    generated_file_contents: dict[str, str] | None = None,
    parent_file_contents: dict[str, str] | None = None,
) -> str:
    """
    Build the validation review prompt from the workflow event.

    Args:
        event: Workflow event with planning/artifacts.
        generated_file_contents: Optional path -> content for files the
            Development Agent generated/modified, fetched fresh from the PR
            branch. When available, lets the LLM actually inspect the code
            instead of only seeing path/status metadata.
        parent_file_contents: Optional path -> content for files declared as
            integration points (`integratesWith`) for newly CREATED files, so
            the LLM can verify the new component is genuinely referenced
            there rather than assuming it based on the plan's intent.
    """
    planning = event.get("planning", {})
    artifacts = event.get("artifacts", {})
    contract = planning.get("implementationContract", {})

    code_section = ""
    if generated_file_contents:
        code_section = (
            "\n--------------------------------------------------\n"
            "GENERATED/MODIFIED FILE CONTENTS (from the PR branch)\n"
            "--------------------------------------------------\n"
        )
        for path, content in generated_file_contents.items():
            truncated = content[:3000] if len(content) > 3000 else content
            code_section += f"\n--- {path} ---\n{truncated}\n"

    parents_section = ""
    if parent_file_contents:
        parents_section = (
            "\n--------------------------------------------------\n"
            "DECLARED PARENT/INTEGRATION FILES (verify new files above are\n"
            "actually referenced here — imported, declared, and rendered/routed)\n"
            "--------------------------------------------------\n"
        )
        for path, content in parent_file_contents.items():
            truncated = content[:3000] if len(content) > 3000 else content
            parents_section += f"\n--- {path} ---\n{truncated}\n"

    return f"""Review the following AI-generated code delivery.

Validate that:
1. The generated files match the implementation plan.
2. Code quality standards are met.
3. No obvious security issues.
4. Test coverage is adequate.
5. Every newly CREATED file that is a UI component/tile/page is ACTUALLY
   integrated — referenced by its declared parent file(s), not just present in
   the repo. Use the GENERATED FILE CONTENTS and DECLARED PARENT FILES sections
   below (when provided) to verify this directly rather than assuming from the
   plan alone.
6. If this ticket involves authentication/login, confirm the success path
   actually navigates to the expected destination (not just that auth state is
   set).

Implementation Plan Summary:
{planning.get("summary", "N/A")}

Requirements:
{json.dumps(planning.get("requirements", []), indent=2)}

Acceptance Criteria:
{json.dumps(planning.get("acceptanceCriteria", []), indent=2)}

Generated Files:
{json.dumps(artifacts.get("generatedFiles", []), indent=2)}

Implementation Contract (file operations planned, including integratesWith):
{json.dumps(contract.get("files", []), indent=2)}
{code_section}
{parents_section}
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
        "unintegratedComponents": [],
        "notes": ""
    }}
}}"""

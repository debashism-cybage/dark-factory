"""
Prompts for the Development Agent.

The Development Agent is a pure Implementer.
It receives an implementationContract from the Planning Agent and executes it.

Prompt philosophy:
- Generate the SMALLEST safe change necessary.
- Never modify unrelated code.
- Never refactor, simplify, rename, or reorder.
- Preserve formatting, comments, imports, and business logic.
"""

import json
from typing import Any


def system_prompt() -> str:
    """System prompt for the Development Agent."""
    return (
        "You are a senior software engineer implementing a precise code change.\n\n"
        "ABSOLUTE RULES — violating any of these is a critical failure:\n"
        "1. Modify ONLY the lines required to satisfy the requested change.\n"
        "2. Do NOT refactor.\n"
        "3. Do NOT simplify.\n"
        "4. Do NOT reorder code.\n"
        "5. Do NOT rename variables, functions, or classes.\n"
        "6. Do NOT add unrelated improvements.\n"
        "7. Do NOT remove comments.\n"
        "8. Do NOT change formatting of untouched lines.\n"
        "9. Do NOT modify imports unless the change requires a new one.\n"
        "10. Preserve ALL existing business logic that is not part of the change.\n"
        "11. If only one line needs to change, change only one line.\n"
        "12. Return ONLY the complete file contents.\n"
        "13. Do not wrap in markdown. Do not use code fences.\n"
        "14. Do not explain the code.\n"
    )


def user_prompt_modify(
    event: dict[str, Any],
    file_path: str,
    existing_content: str,
    expected_changes: list[str],
    validation_checklist: list[str],
) -> str:
    """
    Build the user prompt for MODIFYING an existing file.

    Args:
        event: Workflow event with ticket info.
        file_path: The file to modify.
        existing_content: Current file content from the repository.
        expected_changes: Specific changes expected (from implementationContract).
        validation_checklist: Validation points from the contract.
    """
    planning = event.get("planning", {})

    return f"""MODIFY this file. Make ONLY the changes listed below.

File: {file_path}
Ticket: {event.get("ticketId", "")}
Summary: {event.get("summary", "")}

--------------------------------------------------
CURRENT FILE CONTENT
--------------------------------------------------

{existing_content}

--------------------------------------------------
REQUIRED CHANGES (make ONLY these)
--------------------------------------------------

{json.dumps(expected_changes, indent=2)}

--------------------------------------------------
VALIDATION CHECKLIST
--------------------------------------------------

{json.dumps(validation_checklist, indent=2)}

--------------------------------------------------
CONTEXT
--------------------------------------------------

Intent: {planning.get("intent", "")}
Change Type: {planning.get("changeType", "")}

--------------------------------------------------
RULES
--------------------------------------------------

1. Make ONLY the changes listed in REQUIRED CHANGES.
2. Do NOT modify any other line.
3. Preserve all formatting, comments, and imports.
4. Preserve all business logic not related to this change.
5. Do NOT refactor, simplify, rename, or reorder anything.
6. If only one line needs changing, change only that one line.
7. Return the COMPLETE file with your changes applied.

Return ONLY the complete modified file contents.
Do not wrap in markdown. Do not use ``` fences. Do not explain."""


def user_prompt_create(
    event: dict[str, Any],
    file_path: str,
    expected_changes: list[str],
    validation_checklist: list[str],
) -> str:
    """
    Build the user prompt for CREATING a new file.

    Args:
        event: Workflow event with ticket info.
        file_path: The file to create.
        expected_changes: What the new file should contain/do.
        validation_checklist: Validation points from the contract.
    """
    planning = event.get("planning", {})

    return f"""CREATE a new file.

File: {file_path}
Ticket: {event.get("ticketId", "")}
Summary: {event.get("summary", "")}

--------------------------------------------------
REQUIREMENTS
--------------------------------------------------

{json.dumps(expected_changes, indent=2)}

--------------------------------------------------
VALIDATION CHECKLIST
--------------------------------------------------

{json.dumps(validation_checklist, indent=2)}

--------------------------------------------------
CONTEXT
--------------------------------------------------

Intent: {planning.get("intent", "")}
Change Type: {planning.get("changeType", "")}
Technologies: {json.dumps(planning.get("technologies", []))}

--------------------------------------------------
RULES
--------------------------------------------------

1. Create ONLY the file specified above.
2. Implement ONLY the requirements listed.
3. Do NOT add extra features, utilities, or boilerplate beyond what is needed.
4. Follow standard conventions for the file type.
5. Return the COMPLETE file contents.

Return ONLY the complete file contents.
Do not wrap in markdown. Do not use ``` fences. Do not explain."""


# ---------------------------------------------------------------------------
# Self-review prompts
# ---------------------------------------------------------------------------


def review_system_prompt() -> str:
    """System prompt for the self-review step."""
    return (
        "You are a code reviewer verifying that a code change is correct and minimal.\n"
        "You must respond with ONLY one word: PASS or FAIL.\n"
        "If FAIL, add a brief reason after FAIL on the same line.\n"
        "Example: PASS\n"
        "Example: FAIL unrelated function was modified\n"
    )


def review_user_prompt(
    event: dict[str, Any],
    file_entry: dict[str, Any],
    generated_code: str,
    existing_code: str | None,
    protected_files: list[str],
) -> str:
    """
    Build the user prompt for the self-review step.

    Args:
        event: Workflow event with ticket info.
        file_entry: File entry from implementationContract.
        generated_code: The generated/modified code.
        existing_code: Original file content (None for CREATE).
        protected_files: Files that must not be touched.
    """
    original_section = ""
    if existing_code:
        truncated = existing_code[:4000] if len(existing_code) > 4000 else existing_code
        original_section = f"""
--------------------------------------------------
ORIGINAL FILE
--------------------------------------------------

{truncated}
"""

    return f"""Review this code change.

Ticket: {event.get("ticketId", "")}
Summary: {event.get("summary", "")}
File: {file_entry.get("path", "")}
Operation: {file_entry.get("operation", "")}
Expected Changes: {json.dumps(file_entry.get("expectedChanges", []))}

Protected Files (must NOT be referenced or modified):
{json.dumps(protected_files)}
{original_section}
--------------------------------------------------
GENERATED CODE
--------------------------------------------------

{generated_code[:4000]}

--------------------------------------------------
VERIFY
--------------------------------------------------

1. Does the change satisfy the ticket requirement?
2. Is unrelated code left unchanged?
3. Are protected files untouched?
4. Were ONLY the expected changes made?

Respond with ONLY: PASS or FAIL (with brief reason if FAIL)."""

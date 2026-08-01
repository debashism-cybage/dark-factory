"""
Development Agent Lambda Handler.

Generates or modifies source code via Bedrock based on the planning output,
commits each file to a feature branch on GitHub, and creates a Pull Request.

Before generating code, the agent:
1. Extracts keywords from the Jira ticket and planning output.
2. Searches the target repository for relevant existing files.
3. Builds a RepositoryContext with candidate files.
4. Downloads only the relevant candidate files (ranked, top 3 sent to LLM).
5. Uses an AI reasoning step to decide MODIFY vs CREATE (heuristic fallback).
6. Loads selective architecture knowledge from S3 based on ticket type.

Input: Workflow event with 'planning' (from Planning Agent).
Output: Workflow event enriched with 'artifacts' and status 'DEVELOPMENT_COMPLETE'.
"""

import re
from typing import Any

from shared.bedrock_client import BedrockClient
from shared.config import DevelopmentConfig
from shared.dynamodb_helper import WorkflowTable
from shared.github_client import GitHubClient
from shared.logger import get_logger
from shared.prompts import development as prompts
from shared.s3_helper import S3Helper

logger = get_logger(__name__, agent="development")

# Maximum number of candidate files to download from the repository
MAX_CANDIDATE_FILES = 10

# Maximum candidate files sent to the LLM in prompts (keeps context small)
MAX_CONTEXT_FILES = 3

# Architecture knowledge documents stored in S3
ARCHITECTURE_DOCS: dict[str, str] = {
    "metadata": "architecture/metadata.json",
    "project": "architecture/project.md",
    "architecture": "architecture/architecture.md",
    "repository": "architecture/repository.md",
    "standards": "architecture/standards.md",
}

# Keywords that indicate a UI/frontend ticket
UI_KEYWORDS = {
    "ui", "frontend", "component", "page", "view", "widget", "button",
    "form", "modal", "dialog", "layout", "css", "style", "html", "template",
    "angular", "react", "vue", "login", "dashboard", "screen", "display",
}

# Keywords that indicate a backend ticket
BACKEND_KEYWORDS = {
    "api", "endpoint", "service", "controller", "repository", "database",
    "query", "migration", "schema", "model", "middleware", "server",
    "lambda", "handler", "rest", "graphql", "grpc", "kafka", "queue",
}


# ---------------------------------------------------------------------------
# Step 1: Keyword extraction
# ---------------------------------------------------------------------------


def _extract_keywords(event: dict[str, Any]) -> list[str]:
    """
    Extract search keywords from the ticket and planning output.

    Sources:
        - Ticket summary (split into meaningful words)
        - Ticket description
        - planning.affectedModules
        - planning.filesToGenerate (directory and filename parts)

    Returns:
        Deduplicated list of keywords (lowercased, min 3 chars).
    """
    keywords: set[str] = set()
    planning = event.get("planning", {})

    # From ticket summary — extract meaningful words (3+ chars, no stop words)
    summary = event.get("summary", "")
    stop_words = {
        "the", "and", "for", "from", "with", "this", "that", "have", "has",
        "are", "was", "were", "been", "being", "will", "would", "could",
        "should", "can", "may", "might", "shall", "not", "but", "its",
        "into", "over", "under", "between", "change", "update", "add",
        "remove", "fix", "implement", "create", "delete", "modify",
    }
    words = re.findall(r"[a-zA-Z]+", summary)
    for word in words:
        w = word.lower()
        if len(w) >= 3 and w not in stop_words:
            keywords.add(w)

    # From ticket description
    description = event.get("description", "")
    desc_words = re.findall(r"[a-zA-Z]+", description)
    for word in desc_words:
        w = word.lower()
        if len(w) >= 3 and w not in stop_words:
            keywords.add(w)

    # From affected modules
    for module in planning.get("affectedModules", []):
        parts = re.findall(r"[a-zA-Z]+", module)
        for part in parts:
            if len(part) >= 3:
                keywords.add(part.lower())

    # From filesToGenerate — extract directory names and file stems
    for file_path in planning.get("filesToGenerate", []):
        parts = re.split(r"[/\\.]", file_path)
        for part in parts:
            if len(part) >= 3:
                keywords.add(part.lower())

    return list(keywords)


# ---------------------------------------------------------------------------
# Step 2: Repository search and context building
# ---------------------------------------------------------------------------


def _build_repository_context(
    github: GitHubClient,
    keywords: list[str],
    files_to_generate: list[str],
    branch: str | None = None,
) -> dict[str, Any]:
    """
    Search the repository and build a RepositoryContext object.

    Searches by filename using keywords, then categorizes results
    into components, services, routes, and models.

    Args:
        github: Initialized GitHubClient.
        keywords: Keywords extracted from the ticket.
        files_to_generate: Planned file paths from planning agent.
        branch: Target branch to search.

    Returns:
        RepositoryContext dict.
    """
    # Search for files matching keywords
    search_results = github.search_files_by_keywords(
        keywords=keywords,
        branch=branch,
        max_results=MAX_CANDIDATE_FILES,
    )

    candidate_files = [r["path"] for r in search_results]

    # Also check if any of the planned files already exist
    for file_path in files_to_generate:
        if file_path not in candidate_files:
            if github.file_exists(file_path, branch):
                candidate_files.append(file_path)

    # Categorize files by type
    components: list[str] = []
    services: list[str] = []
    routes: list[str] = []
    models: list[str] = []

    for path in candidate_files:
        path_lower = path.lower()
        if any(kw in path_lower for kw in ["component", "widget", "view", "page"]):
            components.append(path)
        elif any(kw in path_lower for kw in ["service", "client", "api", "helper"]):
            services.append(path)
        elif any(kw in path_lower for kw in ["route", "router", "routing"]):
            routes.append(path)
        elif any(kw in path_lower for kw in ["model", "schema", "entity", "dto"]):
            models.append(path)

    # Detect framework from file extensions and config files
    framework = _detect_framework(candidate_files)

    context: dict[str, Any] = {
        "candidateFiles": candidate_files,
        "existingComponents": components,
        "existingServices": services,
        "existingRoutes": routes,
        "existingModels": models,
        "framework": framework,
        "architectureSummary": "",
    }

    return context


def _detect_framework(file_paths: list[str]) -> str:
    """Detect framework from file paths heuristically."""
    all_paths = " ".join(file_paths).lower()

    if ".tsx" in all_paths or ".jsx" in all_paths:
        if "next" in all_paths:
            return "Next.js"
        return "React"
    if "angular" in all_paths or ".component.ts" in all_paths:
        return "Angular"
    if ".vue" in all_paths:
        return "Vue"
    if ".py" in all_paths:
        if "django" in all_paths:
            return "Django"
        if "flask" in all_paths:
            return "Flask"
        if "fastapi" in all_paths:
            return "FastAPI"
        return "Python"
    if ".java" in all_paths:
        if "spring" in all_paths:
            return "Spring"
        return "Java"
    return ""


# ---------------------------------------------------------------------------
# Step 3: Download candidate files
# ---------------------------------------------------------------------------


def _download_candidate_files(
    github: GitHubClient,
    candidate_files: list[str],
    branch: str | None = None,
) -> dict[str, str]:
    """
    Download content for candidate files (max MAX_CANDIDATE_FILES).

    Args:
        github: Initialized GitHubClient.
        candidate_files: List of file paths to download.
        branch: Target branch.

    Returns:
        Dict of path -> file content.
    """
    files_to_download = candidate_files[:MAX_CANDIDATE_FILES]
    logger.info(
        "Downloading candidate files",
        file_count=len(files_to_download),
        files=files_to_download,
    )
    return github.get_multiple_files(files_to_download, branch)


# ---------------------------------------------------------------------------
# Step 3b: Rank candidate files by relevance (Improvement #2)
# ---------------------------------------------------------------------------


def _rank_candidate_files(
    candidate_files: list[str],
    files_to_generate: list[str],
    keywords: list[str],
    ai_target_files: list[str] | None = None,
) -> list[str]:
    """
    Rank candidate files by relevance and return the top MAX_CONTEXT_FILES.

    Priority:
        1. Exact filename match with filesToGenerate (highest priority).
        2. Files suggested by the AI decision step.
        3. Existing component/service matching ticket keywords (keyword score).

    Args:
        candidate_files: All candidate file paths found in the repo.
        files_to_generate: Planned file paths from planning agent.
        keywords: Extracted keywords from the ticket.
        ai_target_files: Files suggested by the AI decision step (if available).

    Returns:
        Top MAX_CONTEXT_FILES paths, ranked by relevance.
    """
    scored: list[tuple[float, str]] = []

    files_to_generate_lower = {f.lower() for f in files_to_generate}
    ai_targets_lower = {f.lower() for f in (ai_target_files or [])}

    for path in candidate_files:
        path_lower = path.lower()
        score = 0.0

        # Priority 1: Exact filename match with filesToGenerate
        if path_lower in files_to_generate_lower:
            score += 100.0

        # Priority 2: Suggested by AI decision step
        if path_lower in ai_targets_lower:
            score += 50.0

        # Priority 3: Keyword relevance
        keyword_hits = sum(1 for kw in keywords if kw in path_lower)
        score += keyword_hits * 5.0

        scored.append((score, path))

    # Sort descending by score
    scored.sort(key=lambda x: -x[0])

    ranked = [path for _, path in scored[:MAX_CONTEXT_FILES]]

    logger.info(
        "Candidate files ranked",
        top_files=ranked,
        total_candidates=len(candidate_files),
    )

    return ranked


# ---------------------------------------------------------------------------
# Step 4: MODIFY vs CREATE decision (AI-based with heuristic fallback)
# ---------------------------------------------------------------------------


def _decide_action_ai(
    bedrock: BedrockClient,
    event: dict[str, Any],
    repo_context: dict[str, Any],
    architecture_summary: str,
) -> list[dict[str, Any]] | None:
    """
    Use the LLM to decide MODIFY vs CREATE for each file in filesToGenerate.

    This is the primary decision method. If it fails (bad JSON, exception),
    the caller should fall back to heuristic decision.

    Args:
        bedrock: Initialized BedrockClient.
        event: Full workflow event.
        repo_context: RepositoryContext dict.
        architecture_summary: Condensed architecture knowledge.

    Returns:
        List of decision dicts, or None if the AI call fails.
    """
    try:
        decisions = bedrock.converse_json(
            system_prompt=prompts.decision_system_prompt(),
            user_prompt=prompts.decision_user_prompt(
                workflow=event,
                repository_context=repo_context,
                architecture_summary=architecture_summary,
            ),
            max_tokens=2048,
            temperature=0.1,
        )

        # The LLM should return a list; validate structure
        if isinstance(decisions, list):
            validated: list[dict[str, Any]] = []
            for d in decisions:
                if (
                    isinstance(d, dict)
                    and d.get("action") in ("MODIFY", "CREATE")
                    and isinstance(d.get("targetFiles"), list)
                    and len(d["targetFiles"]) > 0
                ):
                    validated.append(d)

            if validated:
                logger.info(
                    "AI decision step successful",
                    decision_count=len(validated),
                )
                return validated

        logger.warning(
            "AI decision returned unexpected format, falling back to heuristic",
            raw_response_type=type(decisions).__name__,
        )
        return None

    except Exception as ex:
        logger.warning(
            "AI decision step failed, falling back to heuristic",
            error=str(ex),
        )
        return None


def _decide_action_heuristic(
    file_path: str,
    candidate_files: list[str],
    existing_contents: dict[str, str],
    keywords: list[str],
) -> dict[str, Any]:
    """
    Heuristic fallback: Decide whether to MODIFY or CREATE.

    Logic:
        1. If file_path already exists in the repo -> MODIFY.
        2. If a candidate file strongly matches the target -> MODIFY that file.
        3. Otherwise -> CREATE.

    Args:
        file_path: The planned file path from filesToGenerate.
        candidate_files: All candidate file paths from repo search.
        existing_contents: Downloaded file contents (path -> content).
        keywords: Extracted keywords for matching.

    Returns:
        Decision dict with action, reason, and targetFiles.
    """
    # Case 1: The exact file already exists
    if file_path in existing_contents:
        return {
            "action": "MODIFY",
            "reason": f"File '{file_path}' already exists in the repository.",
            "targetFiles": [file_path],
        }

    # Case 2: Find the best matching candidate file
    best_match = _find_best_match(file_path, candidate_files, keywords)
    if best_match:
        return {
            "action": "MODIFY",
            "reason": (
                f"Existing file '{best_match}' matches the target "
                f"'{file_path}'. Modifying instead of creating new."
            ),
            "targetFiles": [best_match],
        }

    # Case 3: No suitable existing file found
    return {
        "action": "CREATE",
        "reason": f"No existing file found that matches '{file_path}'. Creating new file.",
        "targetFiles": [file_path],
    }


def _find_best_match(
    target_path: str,
    candidate_files: list[str],
    keywords: list[str],
) -> str | None:
    """
    Find the best matching candidate for a target file path.

    Matches based on filename similarity and keyword overlap.

    Returns:
        Best matching file path, or None if no good match found.
    """
    if not candidate_files:
        return None

    # Extract the filename stem from target
    target_parts = re.split(r"[/\\.]", target_path.lower())
    target_stem_parts = [p for p in target_parts if len(p) >= 3]

    best_score = 0.0
    best_file: str | None = None

    for candidate in candidate_files:
        candidate_parts = re.split(r"[/\\.]", candidate.lower())
        candidate_stem_parts = [p for p in candidate_parts if len(p) >= 3]

        # Score based on shared path segments
        shared = set(target_stem_parts) & set(candidate_stem_parts)
        score = float(len(shared))

        # Bonus: keywords that appear in the candidate path
        candidate_lower = candidate.lower()
        keyword_hits = sum(1 for kw in keywords if kw in candidate_lower)
        score += keyword_hits * 0.5

        if score > best_score:
            best_score = score
            best_file = candidate

    # Require a minimum relevance score to match
    if best_score >= 2.0:
        return best_file

    return None


# ---------------------------------------------------------------------------
# Step 5: Load architecture knowledge from S3 (Improvement #3 — selective)
# ---------------------------------------------------------------------------


def _classify_ticket_type(keywords: list[str]) -> str:
    """
    Classify the ticket as 'ui', 'backend', or 'general' based on keywords.

    Returns:
        'ui', 'backend', or 'general'.
    """
    ui_score = sum(1 for kw in keywords if kw in UI_KEYWORDS)
    backend_score = sum(1 for kw in keywords if kw in BACKEND_KEYWORDS)

    if ui_score > backend_score:
        return "ui"
    if backend_score > ui_score:
        return "backend"
    return "general"


def _load_architecture_knowledge(s3: S3Helper, keywords: list[str]) -> str:
    """
    Load selective architecture knowledge documents from S3.

    Always includes metadata.json, then selects additional docs based on
    ticket classification:
        - UI tickets: repository.md + standards.md
        - Backend tickets: architecture.md + standards.md
        - General: project.md + architecture.md

    If no architecture knowledge is available, returns empty string
    and the agent continues normally.

    Args:
        s3: Initialized S3Helper.
        keywords: Extracted keywords (used to classify ticket type).

    Returns:
        Combined architecture knowledge as a single string.
    """
    ticket_type = _classify_ticket_type(keywords)
    logger.info("Ticket classified for architecture selection", ticket_type=ticket_type)

    # Always include metadata
    docs_to_load: list[str] = [ARCHITECTURE_DOCS["metadata"]]

    # Select relevant docs based on ticket type
    if ticket_type == "ui":
        docs_to_load.append(ARCHITECTURE_DOCS["repository"])
        docs_to_load.append(ARCHITECTURE_DOCS["standards"])
    elif ticket_type == "backend":
        docs_to_load.append(ARCHITECTURE_DOCS["architecture"])
        docs_to_load.append(ARCHITECTURE_DOCS["standards"])
    else:
        # General — include project overview and architecture
        docs_to_load.append(ARCHITECTURE_DOCS["project"])
        docs_to_load.append(ARCHITECTURE_DOCS["architecture"])

    sections: list[str] = []

    for key in docs_to_load:
        try:
            content = s3.download_text(key)
            sections.append(content)
        except Exception as ex:
            logger.warning(
                "Architecture doc not found, skipping",
                key=key,
                error=str(ex),
            )

    if sections:
        logger.info(
            "Architecture knowledge loaded (selective)",
            documents_loaded=len(sections),
            ticket_type=ticket_type,
            docs=docs_to_load,
        )
    else:
        logger.warning("No architecture knowledge available in S3")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Development agent entry point."""
    logger.info("Development agent started", workflow_id=event.get("workflowId"))

    config = DevelopmentConfig()

    workflow_id = event["workflowId"]
    ticket_id = event["ticketId"]
    planning = event["planning"]

    # Initialize services
    github = GitHubClient(
        owner=config.github_repo_owner,
        repo=config.github_repo_name,
        secret_name=config.github_secret_name,
    )
    bedrock = BedrockClient(config.bedrock_model_id)
    s3 = S3Helper(config.bucket_name)
    table = WorkflowTable(config.table_name)

    # ----- Repository-aware code generation pipeline -----

    # Step 1: Extract keywords from ticket
    keywords = _extract_keywords(event)
    logger.info("Keywords extracted", keywords=keywords)

    # Step 2: Search repository and build context
    files_to_generate = planning.get("filesToGenerate", [])
    repo_context = _build_repository_context(
        github=github,
        keywords=keywords,
        files_to_generate=files_to_generate,
    )
    logger.info(
        "Repository context built",
        candidate_count=len(repo_context["candidateFiles"]),
        candidates=repo_context["candidateFiles"],
    )

    # Step 3: Download candidate file contents
    existing_contents = _download_candidate_files(
        github=github,
        candidate_files=repo_context["candidateFiles"],
    )
    logger.info(
        "Candidate files downloaded",
        downloaded_count=len(existing_contents),
    )

    # Step 5: Load selective architecture knowledge from S3
    architecture_knowledge = _load_architecture_knowledge(s3, keywords)
    repo_context["architectureSummary"] = (
        architecture_knowledge[:500] if architecture_knowledge else ""
    )

    # Step 4: AI decision step — MODIFY vs CREATE
    ai_decisions = _decide_action_ai(
        bedrock=bedrock,
        event=event,
        repo_context=repo_context,
        architecture_summary=architecture_knowledge[:1000] if architecture_knowledge else "",
    )

    # Build a lookup from plannedFile -> decision (from AI)
    ai_decision_map: dict[str, dict[str, Any]] = {}
    ai_suggested_files: list[str] = []
    if ai_decisions:
        for d in ai_decisions:
            planned = d.get("plannedFile", "")
            if planned:
                ai_decision_map[planned] = d
                ai_suggested_files.extend(d.get("targetFiles", []))

    # Step 3b: Rank candidate files to top 3 for prompts
    ranked_files = _rank_candidate_files(
        candidate_files=repo_context["candidateFiles"],
        files_to_generate=files_to_generate,
        keywords=keywords,
        ai_target_files=ai_suggested_files,
    )

    # Build a reduced context for prompts (only top 3 files)
    reduced_context: dict[str, Any] = dict(repo_context)
    reduced_context["candidateFiles"] = ranked_files

    # ----- END pipeline -----

    # Create feature branch
    branch = f"feature/{ticket_id}"
    github.ensure_branch(branch)

    # Generate/modify and commit each file
    generated_files: list[dict[str, Any]] = []
    last_commit: dict[str, Any] | None = None

    logger.info(
        "Processing files",
        workflow_id=workflow_id,
        file_count=len(files_to_generate),
    )

    for file_path in files_to_generate:
        # Use AI decision if available, otherwise fall back to heuristic
        if file_path in ai_decision_map:
            decision = ai_decision_map[file_path]
            decision_source = "ai"
            logger.info(
                "Using AI decision",
                file_path=file_path,
                action=decision["action"],
                reason=decision.get("reason", ""),
            )
        else:
            decision = _decide_action_heuristic(
                file_path=file_path,
                candidate_files=repo_context["candidateFiles"],
                existing_contents=existing_contents,
                keywords=keywords,
            )
            decision_source = "heuristic"
            logger.info(
                "Using heuristic decision (AI did not cover this file)",
                file_path=file_path,
                action=decision["action"],
                reason=decision["reason"],
            )

        # Build the appropriate prompt (with selective architecture knowledge)
        sys_prompt = prompts.system_prompt(architecture_knowledge)

        if decision["action"] == "MODIFY":
            target_file = decision["targetFiles"][0]
            existing_code = existing_contents.get(target_file, "")

            # If we don't have the content yet, download it
            if not existing_code:
                try:
                    existing_code = github.get_file_content(target_file)
                except Exception:
                    logger.warning(
                        "Could not download target file, falling back to CREATE",
                        target_file=target_file,
                    )
                    decision = {
                        "action": "CREATE",
                        "reason": f"Could not read '{target_file}', creating new.",
                        "targetFiles": [file_path],
                    }
                    decision_source = "fallback"

        if decision["action"] == "MODIFY":
            target_file = decision["targetFiles"][0]
            existing_code = existing_contents.get(target_file, "")

            user_msg = prompts.user_prompt_modify(
                workflow=event,
                file_path=target_file,
                existing_content=existing_code,
                repository_context=reduced_context,
                reason=decision.get("reason", ""),
            )
            commit_path = target_file
            commit_msg = f"feat({ticket_id}): modify {target_file}"
        else:
            user_msg = prompts.user_prompt_create(
                workflow=event,
                file_path=file_path,
                repository_context=reduced_context,
                reason=decision.get("reason", ""),
            )
            commit_path = file_path
            commit_msg = f"feat({ticket_id}): create {file_path}"

        # Call Bedrock for code generation
        logger.info(
            "Generating code",
            file_path=commit_path,
            action=decision["action"],
            decision_source=decision_source,
        )
        code = bedrock.converse(
            system_prompt=sys_prompt,
            user_prompt=user_msg,
            max_tokens=8192,
        )

        # Commit to GitHub
        last_commit = github.commit_file(
            branch=branch,
            path=commit_path,
            content=code,
            message=commit_msg,
        )

        generated_files.append(
            {
                "path": commit_path,
                "size": len(code),
                "action": decision["action"],
                "reason": decision.get("reason", ""),
                "decisionSource": decision_source,
            }
        )

    # Create or reuse Pull Request
    pr = github.ensure_pull_request(
        branch=branch,
        ticket_id=ticket_id,
        workflow_id=workflow_id,
    )

    # Build artifacts summary
    artifacts = event.get("artifacts", {})
    artifacts.update(
        {
            "repository": f"{config.github_repo_owner}/{config.github_repo_name}",
            "branch": branch,
            "commitSha": last_commit["commit"]["sha"] if last_commit else "",
            "pullRequest": pr["url"],
            "pullRequestNumber": pr["number"],
            "generatedFiles": generated_files,
            "repositoryContext": {
                "candidateFiles": repo_context["candidateFiles"],
                "rankedFiles": ranked_files,
                "framework": repo_context["framework"],
            },
        }
    )

    # Store code generation artifact in S3
    s3.upload_json(
        f"artifacts/{workflow_id}-generated-code.json",
        {
            "files": generated_files,
            "branch": branch,
            "pullRequest": pr["url"],
            "repositoryContext": repo_context,
            "rankedFiles": ranked_files,
            "keywords": keywords,
            "aiDecisions": ai_decisions,
        },
    )

    # Update DynamoDB
    table.update_status(
        workflow_id=workflow_id,
        status="DEVELOPMENT_COMPLETE",
        agent="development",
        artifacts=artifacts,
    )

    # Enrich workflow event
    event["status"] = "DEVELOPMENT_COMPLETE"
    event["currentAgent"] = "development"
    event["artifacts"] = artifacts

    logger.info(
        "Development complete",
        workflow_id=workflow_id,
        files_processed=len(generated_files),
        pr_url=pr["url"],
    )

    return event

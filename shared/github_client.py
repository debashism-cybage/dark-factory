"""
Unified GitHub REST API client.

Merges read-only repository discovery (architecture agent) with
write operations (development agent): branch management, commits, PRs.

Retrieves credentials from Secrets Manager via shared.secrets.

Usage:
    from shared.github_client import GitHubClient

    client = GitHubClient(
        owner="my-org",
        repo="my-repo",
        secret_name="github/pat",
    )

    # Read operations
    summary = client.get_repository_summary()
    tree = client.get_repository_tree()
    content = client.get_file_content("src/main.py")

    # Write operations
    client.ensure_branch("feature/TICKET-123")
    client.commit_file("feature/TICKET-123", "src/new.py", code, "Add new file")
    pr = client.ensure_pull_request("feature/TICKET-123", "TICKET-123", "WF-ABC")
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from shared.logger import get_logger
from shared.secrets import get_github_token

logger = get_logger(__name__)


class GitHubClient:
    """
    Full-featured GitHub REST API client.

    Combines repository discovery (read) and code management (write)
    into a single reusable class.
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        secret_name: str,
        default_branch: str = "main",
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.default_branch = default_branch

        self.token = get_github_token(secret_name)
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        logger.info("GitHubClient initialized", owner=owner, repo=repo)

    # -----------------------------------------------------------------------
    # HTTP helpers
    # -----------------------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a GitHub API request."""
        url = f"{self.base_url}{endpoint}"

        if params:
            url += "?" + urllib.parse.urlencode(params)

        data = json.dumps(body).encode() if body else None

        headers = dict(self.headers)
        if body:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url=url,
            method=method,
            headers=headers,
            data=data,
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                if response_body:
                    return json.loads(response_body)
                return None

        except urllib.error.HTTPError as ex:
            error_body = ex.read().decode("utf-8")
            logger.error(
                "GitHub API error",
                status_code=ex.code,
                endpoint=endpoint,
                error=error_body[:500],
            )
            raise GitHubAPIError(ex.code, error_body) from ex

    # -----------------------------------------------------------------------
    # Repository discovery (read operations)
    # -----------------------------------------------------------------------

    def get_default_branch(self) -> str:
        """Get the repository's default branch name."""
        repo = self._request("GET", "")
        return repo.get("default_branch", self.default_branch)

    def get_repository(self) -> dict[str, Any]:
        """Get repository metadata."""
        return self._request("GET", "")

    def get_repository_tree(self, branch: str | None = None) -> list[dict[str, Any]]:
        """Get the full file tree of the repository."""
        branch = branch or self.default_branch
        tree = self._request("GET", f"/git/trees/{branch}?recursive=1")
        return tree.get("tree", [])

    def get_all_files(self, branch: str | None = None) -> list[dict[str, Any]]:
        """Get only file entries (blobs) from the repository tree."""
        tree = self.get_repository_tree(branch)
        return [item for item in tree if item.get("type") == "blob"]

    def get_all_directories(self, branch: str | None = None) -> list[dict[str, Any]]:
        """Get only directory entries (trees) from the repository tree."""
        tree = self.get_repository_tree(branch)
        return [item for item in tree if item.get("type") == "tree"]

    def list_directory(self, path: str = "", branch: str | None = None) -> list[dict[str, Any]]:
        """List contents of a specific directory."""
        branch = branch or self.default_branch
        contents = self._request("GET", f"/contents/{path}", params={"ref": branch})
        if isinstance(contents, dict):
            return [contents]
        return contents

    def get_file(self, path: str, branch: str | None = None) -> dict[str, Any]:
        """Get GitHub metadata for a file."""
        branch = branch or self.default_branch
        return self._request("GET", f"/contents/{path}", params={"ref": branch})

    def get_file_content(self, path: str, branch: str | None = None) -> str:
        """
        Get the decoded text content of a file.

        Args:
            path: File path within the repository.
            branch: Branch name (defaults to default_branch).

        Returns:
            Decoded file content as string.
        """
        metadata = self.get_file(path, branch)

        if metadata.get("type") != "file":
            raise ValueError(f"'{path}' is not a file.")

        if metadata.get("encoding") == "base64":
            return base64.b64decode(metadata["content"]).decode("utf-8", errors="replace")

        download_url = metadata.get("download_url")
        if not download_url:
            raise ValueError(f"No download URL available for '{path}'")

        request = urllib.request.Request(download_url, headers=self.headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8")

    def get_multiple_files(self, paths: list[str], branch: str | None = None) -> dict[str, str]:
        """Read multiple files, skipping any that fail."""
        result: dict[str, str] = {}
        for path in paths:
            try:
                result[path] = self.get_file_content(path, branch)
            except Exception as ex:
                logger.warning("Unable to read file", path=path, error=str(ex))
        return result

    def file_exists(self, path: str, branch: str | None = None) -> bool:
        """Check if a file exists in the repository."""
        try:
            self.get_file(path, branch)
            return True
        except Exception:
            return False

    def find_files(
        self,
        extensions: list[str] | None = None,
        contains: str | None = None,
        branch: str | None = None,
    ) -> list[str]:
        """Search files by extension and/or name substring."""
        files = self.get_all_files(branch)
        results: list[str] = []

        for item in files:
            path = item["path"]
            if extensions and not any(path.endswith(ext) for ext in extensions):
                continue
            if contains and contains.lower() not in path.lower():
                continue
            results.append(path)

        return results

    def search_files_by_keywords(
        self,
        keywords: list[str],
        branch: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Search repository files by multiple keywords matched against file paths.

        Each file is scored by how many keywords match its path (case-insensitive).
        Results are sorted by relevance (number of keyword hits) descending.

        Args:
            keywords: List of keywords to match against file paths.
            branch: Branch to search (defaults to default_branch).
            max_results: Maximum number of results to return.

        Returns:
            List of dicts with 'path' and 'score' keys, sorted by score descending.
        """
        files = self.get_all_files(branch)
        scored: list[dict[str, Any]] = []

        normalized_keywords = [kw.lower() for kw in keywords if kw.strip()]

        for item in files:
            path = item["path"]
            path_lower = path.lower()

            # Score: count how many keywords appear in the file path
            score = sum(1 for kw in normalized_keywords if kw in path_lower)

            if score > 0:
                scored.append({"path": path, "score": score})

        # Sort by score descending, then path alphabetically for stability
        scored.sort(key=lambda x: (-x["score"], x["path"]))

        return scored[:max_results]

    def get_repository_summary(self, branch: str | None = None) -> dict[str, Any]:
        """Get a lightweight summary of the repository structure."""
        files = self.get_all_files(branch)
        directories = self.get_all_directories(branch)

        extensions: dict[str, int] = {}
        for file in files:
            name = file["path"]
            ext = "." + name.rsplit(".", 1)[1] if "." in name else "no_extension"
            extensions[ext] = extensions.get(ext, 0) + 1

        return {
            "repository": f"{self.owner}/{self.repo}",
            "branch": branch or self.default_branch,
            "totalFiles": len(files),
            "totalDirectories": len(directories),
            "extensions": dict(sorted(extensions.items())),
        }

    def get_project_context(self, branch: str | None = None) -> dict[str, Any]:
        """
        Read important project files for architecture knowledge generation.

        Returns content of common project config files plus a repository summary.
        """
        important_files = [
            "README.md",
            "package.json",
            "angular.json",
            "tsconfig.json",
            "pom.xml",
            "build.gradle",
            "settings.gradle",
            "Dockerfile",
            "docker-compose.yml",
            ".gitignore",
            "requirements.txt",
            "pyproject.toml",
            "Makefile",
            "template.yaml",
        ]

        context: dict[str, Any] = self.get_multiple_files(important_files, branch)
        context["repositorySummary"] = self.get_repository_summary(branch)
        return context

    # -----------------------------------------------------------------------
    # Write operations (branch, commit, PR)
    # -----------------------------------------------------------------------

    def branch_has_merged_pull_request(self, branch_name: str) -> bool:
        """
        Check whether ANY pull request (in any state) from branch_name was
        ever merged into the base branch.

        Why this matters: a feature branch is meant to carry exactly one
        ticket's work through exactly one merge. If its PR was already
        merged and the Development Agent is invoked again for the same
        ticket (e.g. a re-triggered workflow, or a ticket reopened after
        being reverted), reusing/continuing to commit to that same branch
        stacks a second, unrelated set of changes on top of history that
        has already landed in main — even if main later reverted the merge
        commit, the branch and main have now diverged in a way that cannot
        be cleanly auto-merged (main says "delete this code", the branch
        says "keep extending it"). This is exactly what happened across
        PRs #15/#18/#20/#21 for feature/SCRUM-16 in angular-dev: PR #18
        merged the branch, main reverted it, and the branch was reused
        for two more rounds of unrelated commits, producing a PR with
        irreconcilable merge conflicts.

        Returns:
            True if any PR (open, closed, or merged) with this branch as
            head has a non-null merged_at.
        """
        try:
            prs = self._request(
                "GET",
                "/pulls",
                params={"state": "all", "head": f"{self.owner}:{branch_name}"},
            )
        except GitHubAPIError as ex:
            logger.warning(
                "Could not check merged-PR history for branch",
                branch=branch_name,
                error=str(ex),
            )
            return False

        return any(pr.get("merged_at") for pr in (prs or []))

    def reset_branch_to_base(self, branch_name: str, base_branch: str | None = None) -> None:
        """
        Force the branch ref to point at base_branch's current tip,
        discarding any commits the branch previously had.

        This is intentionally destructive, but scoped ONLY to the ephemeral
        per-ticket working branch (feature/{ticket_id}) created and owned by
        the Development Agent -- never to base_branch/main. It is the
        correct action when the branch's prior PR has already been merged
        (see branch_has_merged_pull_request): that branch's history is
        already captured in main, so starting the next round of work fresh
        from main's tip is safe and is what prevents unresolvable merge
        conflicts from accumulating.

        Args:
            branch_name: The feature branch to reset.
            base_branch: Branch to reset from (defaults to main).
        """
        base_branch = base_branch or self.default_branch
        ref = self._request("GET", f"/git/ref/heads/{base_branch}")
        base_sha = ref["object"]["sha"]

        self._request(
            "PATCH",
            f"/git/refs/heads/{branch_name}",
            body={"sha": base_sha, "force": True},
        )
        logger.info(
            "Branch reset to base tip (previous PR already merged)",
            branch=branch_name,
            base=base_branch,
            new_sha=base_sha,
        )

    def sync_branch_with_base(
        self,
        branch_name: str,
        base_branch: str | None = None,
    ) -> dict[str, Any]:
        """
        Merge the latest base_branch (default: main) into branch_name.

        Why this exists: a feature branch is created once from main's tip,
        but a ticket's development can span multiple Development Agent
        invocations (including adaptive-replan retries) over an extended
        period. Other work can land on main in the meantime. If the feature
        branch is never re-synced, it silently drifts further from main on
        every retry, and the eventual PR shows accumulated merge conflicts
        that have nothing to do with the ticket itself. This is called
        every time `ensure_branch` finds the branch already exists, so the
        branch is always brought up to date with main BEFORE any further
        GitHub read/write happens against it — for every ticket, generically.

        Uses GitHub's Merge API (a real merge commit on branch_name), not a
        destructive reset, so it never discards the branch's own commits.

        Returns:
            Dict describing the outcome:
                {"synced": bool, "conflict": bool, "alreadyUpToDate": bool,
                 "message": str}
            On a real merge conflict (branch_name has changes to the same
            lines as base_branch), this returns conflict=True rather than
            raising — the pipeline logs it and continues with the branch's
            existing content rather than aborting, since automatic conflict
            resolution isn't safe to attempt here. Callers should surface
            this in artifacts/logs for human visibility.
        """
        base_branch = base_branch or self.default_branch

        try:
            result = self._request(
                "POST",
                "/merges",
                body={
                    "base": branch_name,
                    "head": base_branch,
                    "commit_message": f"chore: sync {branch_name} with latest {base_branch}",
                },
            )
        except GitHubAPIError as ex:
            if ex.status_code == 409:
                logger.warning(
                    "Merge conflict syncing branch with base — continuing with "
                    "existing branch content; PR may show conflicts that need "
                    "manual resolution",
                    branch=branch_name,
                    base=base_branch,
                )
                return {
                    "synced": False,
                    "conflict": True,
                    "alreadyUpToDate": False,
                    "message": ex.message,
                }
            logger.warning(
                "Failed to sync branch with base",
                branch=branch_name,
                base=base_branch,
                error=str(ex),
            )
            return {
                "synced": False,
                "conflict": False,
                "alreadyUpToDate": False,
                "message": str(ex),
            }

        if result is None:
            # 204 No Content: branch_name already contains base_branch's tip.
            logger.info(
                "Branch already up to date with base",
                branch=branch_name,
                base=base_branch,
            )
            return {
                "synced": True,
                "conflict": False,
                "alreadyUpToDate": True,
                "message": "",
            }

        logger.info(
            "Branch synced with latest base",
            branch=branch_name,
            base=base_branch,
            merge_sha=result.get("sha"),
        )
        return {
            "synced": True,
            "conflict": False,
            "alreadyUpToDate": False,
            "message": "",
        }

    def ensure_branch(
        self, branch_name: str, base_branch: str | None = None
    ) -> dict[str, Any] | None:
        """
        Ensure a branch exists and is safe to keep working on.

        If the branch already exists, this checks whether it already had a
        PR merged into base_branch (see branch_has_merged_pull_request):
          - If YES: the branch's prior work has already landed in main (or
            been explicitly reverted there). Continuing to commit on top of
            it would stack new/unrelated changes onto history main no
            longer wants, producing unresolvable merge conflicts (this is
            exactly what happened to feature/SCRUM-16 in angular-dev across
            PRs #15/#18/#20/#21). The branch is reset to base_branch's
            current tip instead (see reset_branch_to_base), so the next
            round of work starts clean.
          - If NO: the branch is mid-flight (e.g. an adaptive-replan retry
            on work that hasn't been merged yet), so it is synced with the
            latest base_branch instead (see sync_branch_with_base) — this
            is the "always take latest pull of main before doing anything
            with GitHub" step, applied generically for every ticket.

        Args:
            branch_name: Target branch name.
            base_branch: Branch to fork from (defaults to main).

        Returns:
            A dict describing what happened — {"action": "reset", ...} if
            the branch had a merged PR and was reset to base_branch's tip,
            or the sync result dict (with an added "action": "synced" key)
            if the branch was mid-flight and got synced — or None if the
            branch was newly created (already at base_branch's tip, no
            further action needed).
        """
        base_branch = base_branch or self.default_branch

        # Check if branch already exists
        try:
            self._request("GET", f"/git/ref/heads/{branch_name}")
        except GitHubAPIError:
            # Branch does not exist -- create it fresh from base_branch's tip.
            ref = self._request("GET", f"/git/ref/heads/{base_branch}")
            sha = ref["object"]["sha"]
            self._request(
                "POST",
                "/git/refs",
                body={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
            logger.info("Branch created", branch=branch_name, base=base_branch)
            return None

        if self.branch_has_merged_pull_request(branch_name):
            logger.warning(
                "Branch's previous PR was already merged -- resetting to "
                "latest base instead of reusing stale/merged history",
                branch=branch_name,
                base=base_branch,
            )
            self.reset_branch_to_base(branch_name, base_branch)
            return {
                "action": "reset",
                "synced": True,
                "conflict": False,
                "alreadyUpToDate": False,
                "message": "",
            }

        logger.info(
            "Branch already exists (no merged PR yet), syncing with latest base branch first",
            branch=branch_name,
            base=base_branch,
        )
        result = self.sync_branch_with_base(branch_name, base_branch)
        result["action"] = "synced"
        return result

    def commit_file(
        self,
        branch: str,
        path: str,
        content: str,
        message: str,
    ) -> dict[str, Any]:
        """
        Create or update a file in the repository.

        Args:
            branch: Target branch.
            path: File path within the repo.
            content: File content (text).
            message: Commit message.

        Returns:
            GitHub API response with commit info.
        """
        url_path = f"/contents/{path}"
        encoded = base64.b64encode(content.encode()).decode()

        body: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }

        # If file exists, include its SHA for update
        try:
            existing = self._request("GET", url_path, params={"ref": branch})
            body["sha"] = existing["sha"]
        except GitHubAPIError:
            pass

        result = self._request("PUT", url_path, body=body)
        logger.info("File committed", path=path, branch=branch)
        return result

    def ensure_pull_request(
        self,
        branch: str,
        ticket_id: str,
        workflow_id: str,
        base_branch: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a PR or return existing one for the branch.

        Args:
            branch: Source branch (head).
            ticket_id: Jira ticket ID for the PR title.
            workflow_id: Workflow ID for traceability.
            base_branch: Target branch (defaults to main).

        Returns:
            Dict with 'number' and 'url' keys.
        """
        base_branch = base_branch or self.default_branch

        # Check for existing open PR
        prs = self._request(
            "GET",
            "/pulls",
            params={"state": "open", "head": f"{self.owner}:{branch}"},
        )

        if prs:
            logger.info("Using existing PR", pr_number=prs[0]["number"])
            return {"number": prs[0]["number"], "url": prs[0]["html_url"]}

        # Create new PR
        pr = self._request(
            "POST",
            "/pulls",
            body={
                "title": f"[Dark Factory] {ticket_id}",
                "head": branch,
                "base": base_branch,
                "body": (
                    f"## Dark Factory AI Pull Request\n\n"
                    f"**Workflow:** {workflow_id}\n\n"
                    f"**Ticket:** {ticket_id}\n\n"
                    f"Generated automatically by Dark Factory."
                ),
            },
        )

        logger.info("PR created", pr_number=pr["number"])
        return {"number": pr["number"], "url": pr["html_url"]}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API {status_code}: {message}")

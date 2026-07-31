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

        context = self.get_multiple_files(important_files, branch)
        context["repositorySummary"] = self.get_repository_summary(branch)
        return context

    # -----------------------------------------------------------------------
    # Write operations (branch, commit, PR)
    # -----------------------------------------------------------------------

    def ensure_branch(self, branch_name: str, base_branch: str | None = None) -> None:
        """
        Ensure a branch exists. Creates it from base_branch if it doesn't.

        Args:
            branch_name: Target branch name.
            base_branch: Branch to fork from (defaults to main).
        """
        base_branch = base_branch or self.default_branch

        # Check if branch already exists
        try:
            self._request("GET", f"/git/ref/heads/{branch_name}")
            logger.info("Branch already exists", branch=branch_name)
            return
        except GitHubAPIError:
            pass

        # Get SHA of base branch
        ref = self._request("GET", f"/git/ref/heads/{base_branch}")
        sha = ref["object"]["sha"]

        # Create branch
        self._request(
            "POST",
            "/git/refs",
            body={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        logger.info("Branch created", branch=branch_name, base=base_branch)

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

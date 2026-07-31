import base64
import json
import logging
import os

import boto3
import urllib.request
import urllib.parse
import urllib.error

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class GitHubClient:
    """
    GitHub REST API client.

    Reads credentials from AWS Secrets Manager and provides helper
    methods for repository discovery.

    Environment Variables
    ---------------------
    GITHUB_SECRET_NAME
    GITHUB_REPO_OWNER
    GITHUB_REPO_NAME
    DEFAULT_BRANCH
    """

    def __init__(self):
        self.owner = os.environ["GITHUB_REPO_OWNER"]
        self.repo = os.environ["GITHUB_REPO_NAME"]
        self.default_branch = os.getenv("DEFAULT_BRANCH", "main")

        secret_name = os.environ["GITHUB_SECRET_NAME"]

        secrets = boto3.client("secretsmanager")

        secret = secrets.get_secret_value(SecretId=secret_name)

        credentials = json.loads(secret["SecretString"])

        self.token = (
            credentials.get("token")
            or credentials.get("github_token")
            or credentials.get("pat")
        )

        if not self.token:
            raise ValueError(
                "GitHub Personal Access Token not found in Secrets Manager."
            )

        self.base_url = f"https://api.github.com/repos/{self.owner}/{self.repo}"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        logger.info("Initialized GitHub client for %s/%s", self.owner, self.repo)

    def _request(self, method, endpoint, params=None):

        url = f"{self.base_url}{endpoint}"

        if params:
            url += "?" + urllib.parse.urlencode(params)

        request = urllib.request.Request(
            url=url,
            method=method,
            headers=self.headers
        )

        try:

            with urllib.request.urlopen(request, timeout=30) as response:

                body = response.read().decode("utf-8")

                if body:
                    return json.loads(body)

                return None

        except urllib.error.HTTPError as ex:

            error = ex.read().decode("utf-8")

            logger.error(error)

            raise Exception(
                f"GitHub API Error {ex.code}: {error}"
            )

    def get_default_branch(self):
        """
        Returns the repository's default branch.
        """
        repo = self._request("GET", "")
        return repo.get("default_branch", self.default_branch)

    def file_exists(self, path, branch=None):
        """
        Returns True if a file exists.
        """
        try:
            self.get_file(path, branch)
            return True
        except Exception:
            return False

    def get_repository(self):
        """
        Returns repository metadata.
        """
        return self._request("GET", "")

    def get_repository_tree(self, branch=None):
        """
        Returns every file and directory in the repository.
        """
        branch = branch or self.get_default_branch()

        tree = self._request(
            "GET",
            f"/git/trees/{branch}?recursive=1",
        )

        return tree.get("tree", [])

    def list_directory(self, path="", branch=None):
        """
        Returns the contents of a directory.
        """
        branch = branch or self.get_default_branch()
        endpoint = f"/contents/{path}"

        contents = self._request(
            "GET",
            endpoint,
            params={"ref": branch},
        )

        if isinstance(contents, dict):
            return [contents]

        return contents

    def get_all_files(self, branch=None):
        """
        Returns only files from the repository tree.
        """
        tree = self.get_repository_tree(branch)
        return [item for item in tree if item.get("type") == "blob"]

    def get_all_directories(self, branch=None):
        """
        Returns only directories from the repository tree.
        """
        tree = self.get_repository_tree(branch)
        return [item for item in tree if item.get("type") == "tree"]

    def get_file(self, path, branch=None):
        """
        Returns GitHub metadata for a file.
        """
        branch = branch or self.get_default_branch()
        return self._request(
            "GET",
            f"/contents/{path}",
            params={"ref": branch},
        )

    def get_file_content(self, path, branch=None):
        """
        Returns the decoded text content of a file.
        """
        metadata = self.get_file(path, branch)

        if metadata.get("type") != "file":
            raise Exception(f"{path} is not a file.")

        if metadata.get("encoding") == "base64":
            content = base64.b64decode(metadata["content"]).decode(
                "utf-8", errors="replace"
            )
            return content

        download_url = metadata.get("download_url")
        if not download_url:
            raise Exception(f"No download URL available for {path}")

        request = urllib.request.Request(
            download_url,
            headers=self.headers
        )

        with urllib.request.urlopen(request, timeout=30) as response:

            return response.read().decode("utf-8")

    def download_file(self, path, destination, branch=None):
        """
        Downloads a repository file to a local path.
        """
        content = self.get_file_content(path, branch)

        with open(destination, "w", encoding="utf-8") as file:
            file.write(content)

        logger.info("Downloaded %s -> %s", path, destination)
        return destination

    def get_multiple_files(self, paths, branch=None):
        """
        Reads multiple files and returns a dictionary.
        """
        result = {}

        for path in paths:
            try:
                result[path] = self.get_file_content(path, branch)
            except Exception as ex:
                logger.warning("Unable to read %s : %s", path, ex)

        return result

    def find_files(self, extensions=None, contains=None, branch=None):
        """
        Search repository files by extension and/or filename.
        """
        files = self.get_all_files(branch)

        results = []

        for item in files:
            path = item["path"]

            if extensions:
                if not any(path.endswith(ext) for ext in extensions):
                    continue

            if contains:
                if contains.lower() not in path.lower():
                    continue

            results.append(path)

        return results

    def get_repository_summary(self, branch=None):
        """
        Returns a lightweight repository summary.
        """
        files = self.get_all_files(branch)
        directories = self.get_all_directories(branch)

        extensions = {}

        for file in files:
            name = file["path"]

            if "." in name:
                ext = "." + name.split(".")[-1]
            else:
                ext = "no_extension"

            extensions[ext] = extensions.get(ext, 0) + 1

        return {
            "repository": f"{self.owner}/{self.repo}",
            "branch": branch or self.get_default_branch(),
            "totalFiles": len(files),
            "totalDirectories": len(directories),
            "extensions": dict(sorted(extensions.items())),
        }

    def get_project_context(self, branch=None):
        """
        Reads the important project files for architecture generation.
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
        ]

        context = self.get_multiple_files(important_files, branch)
        context["repositorySummary"] = self.get_repository_summary(branch)
        return context
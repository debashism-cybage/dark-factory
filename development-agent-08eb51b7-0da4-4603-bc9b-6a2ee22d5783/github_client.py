import json
import base64
import urllib.request
import urllib.error


class GitHubClient:

    def __init__(self, token, owner, repo):
        self.token = token
        self.owner = owner
        self.repo = repo

    def request(self, url, method="GET", body=None):

        req = urllib.request.Request(
            url=url,
            method=method
        )

        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")

        if body:
            req.add_header("Content-Type", "application/json")
            body = json.dumps(body).encode()

        try:
            with urllib.request.urlopen(req, data=body) as response:
                return json.loads(response.read().decode())

        except urllib.error.HTTPError as e:
            print(e.read().decode())
            raise

    def ensure_branch(self, branch_name):

        try:
            self.request(
                f"https://api.github.com/repos/{self.owner}/{self.repo}/git/ref/heads/{branch_name}"
            )

            print(f"Branch exists: {branch_name}")
            return

        except:
            pass

        ref = self.request(
            f"https://api.github.com/repos/{self.owner}/{self.repo}/git/ref/heads/main"
        )

        sha = ref["object"]["sha"]

        self.request(
            f"https://api.github.com/repos/{self.owner}/{self.repo}/git/refs",
            "POST",
            {
                "ref": f"refs/heads/{branch_name}",
                "sha": sha
            }
        )

        print(f"Created branch: {branch_name}")

    def commit_file(self, branch, path, content, message):

        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/contents/{path}"

        body = {
            "message": message,
            "content": base64.b64encode(
                content.encode()
            ).decode(),
            "branch": branch
        }

        try:
            existing = self.request(
                f"{url}?ref={branch}"
            )

            body["sha"] = existing["sha"]

        except:
            pass

        return self.request(
            url,
            "PUT",
            body
        )

    def ensure_pull_request(self, branch, ticket_id, workflow_id):

        prs = self.request(
            f"https://api.github.com/repos/{self.owner}/{self.repo}/pulls?state=open&head={self.owner}:{branch}"
        )

        if len(prs) > 0:

            print("Using existing PR")

            return {
                "number": prs[0]["number"],
                "url": prs[0]["html_url"]
            }

        pr = self.request(
            f"https://api.github.com/repos/{self.owner}/{self.repo}/pulls",
            "POST",
            {
                "title": f"AI Generated Changes for {ticket_id}",
                "head": branch,
                "base": "main",
                "body": f"""
## Dark Factory AI Pull Request

Workflow: {workflow_id}

Ticket: {ticket_id}

Generated automatically by Dark Factory.
"""
            }
        )

        print("Created PR")

        return {
            "number": pr["number"],
            "url": pr["html_url"]
        }
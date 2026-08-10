"""
Tests for shared.github_client — specifically the branch-sync behavior in
ensure_branch/sync_branch_with_base.

These reproduce the scenario that caused PRs to open with unrelated merge
conflicts: a feature branch created once from main, then never re-synced
across multiple Development Agent invocations while other work landed on
main in the meantime.
"""

from unittest.mock import MagicMock, patch

import pytest

from shared.github_client import GitHubAPIError, GitHubClient


@pytest.fixture
def client():
    with patch("shared.github_client.get_github_token", return_value="fake-token"):
        return GitHubClient(owner="acme", repo="widgets", secret_name="fake-secret")


class TestSyncBranchWithBase:
    def test_merges_successfully(self, client):
        client._request = MagicMock(return_value={"sha": "merged123"})

        result = client.sync_branch_with_base("feature/TICKET-1")

        assert result == {
            "synced": True,
            "conflict": False,
            "alreadyUpToDate": False,
            "message": "",
        }
        client._request.assert_called_once_with(
            "POST",
            "/merges",
            body={
                "base": "feature/TICKET-1",
                "head": "main",
                "commit_message": "chore: sync feature/TICKET-1 with latest main",
            },
        )

    def test_already_up_to_date_returns_204(self, client):
        # GitHub's Merge API returns 204 No Content (None from _request)
        # when base already contains head's tip.
        client._request = MagicMock(return_value=None)

        result = client.sync_branch_with_base("feature/TICKET-1")

        assert result == {
            "synced": True,
            "conflict": False,
            "alreadyUpToDate": True,
            "message": "",
        }

    def test_merge_conflict_returns_conflict_flag_not_raise(self, client):
        client._request = MagicMock(side_effect=GitHubAPIError(409, "Merge conflict"))

        result = client.sync_branch_with_base("feature/TICKET-1")

        assert result["conflict"] is True
        assert result["synced"] is False

    def test_other_api_error_does_not_raise(self, client):
        client._request = MagicMock(side_effect=GitHubAPIError(500, "Server error"))

        result = client.sync_branch_with_base("feature/TICKET-1")

        assert result["conflict"] is False
        assert result["synced"] is False

    def test_uses_custom_base_branch(self, client):
        client._request = MagicMock(return_value={"sha": "merged123"})

        client.sync_branch_with_base("feature/TICKET-1", base_branch="develop")

        client._request.assert_called_once_with(
            "POST",
            "/merges",
            body={
                "base": "feature/TICKET-1",
                "head": "develop",
                "commit_message": "chore: sync feature/TICKET-1 with latest develop",
            },
        )


class TestEnsureBranchSyncsExistingBranch:
    """
    The core fix: ensure_branch must ALWAYS sync an already-existing branch
    with the latest base before returning, so the branch never silently
    drifts from main across repeated Development Agent invocations
    (including adaptive-replan retries).
    """

    def test_existing_branch_triggers_sync(self, client):
        # First call: GET /git/ref/heads/{branch} succeeds -> branch exists.
        client._request = MagicMock(return_value={"object": {"sha": "abc123"}})
        client.sync_branch_with_base = MagicMock(
            return_value={
                "synced": True,
                "conflict": False,
                "alreadyUpToDate": False,
                "message": "",
            }
        )

        result = client.ensure_branch("feature/TICKET-1")

        client.sync_branch_with_base.assert_called_once_with("feature/TICKET-1", "main")
        assert result["synced"] is True

    def test_existing_branch_with_conflict_is_surfaced(self, client):
        client._request = MagicMock(return_value={"object": {"sha": "abc123"}})
        client.sync_branch_with_base = MagicMock(
            return_value={
                "synced": False,
                "conflict": True,
                "alreadyUpToDate": False,
                "message": "conflict",
            }
        )

        result = client.ensure_branch("feature/TICKET-1")

        assert result["conflict"] is True

    def test_new_branch_created_from_base_tip_no_sync_needed(self, client):
        # First call (GET ref) raises 404 -> branch does not exist.
        # Second call (GET base ref) succeeds.
        # Third call (POST create ref) succeeds.
        client._request = MagicMock(
            side_effect=[
                GitHubAPIError(404, "Not Found"),
                {"object": {"sha": "main-tip-sha"}},
                {"ref": "refs/heads/feature/TICKET-1"},
            ]
        )
        client.sync_branch_with_base = MagicMock()

        result = client.ensure_branch("feature/TICKET-1")

        # A newly created branch is already at main's tip -- no sync call.
        client.sync_branch_with_base.assert_not_called()
        assert result is None

    def test_respects_custom_base_branch_for_new_branch(self, client):
        client._request = MagicMock(
            side_effect=[
                GitHubAPIError(404, "Not Found"),
                {"object": {"sha": "develop-tip-sha"}},
                {"ref": "refs/heads/feature/TICKET-1"},
            ]
        )

        client.ensure_branch("feature/TICKET-1", base_branch="develop")

        # Verify the branch was created from develop's tip, not main's.
        create_call = client._request.call_args_list[-1]
        assert create_call.kwargs["body"]["sha"] == "develop-tip-sha"

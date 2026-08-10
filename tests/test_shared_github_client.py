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


class TestBranchHasMergedPullRequest:
    def test_true_when_any_pr_has_merged_at(self, client):
        client._request = MagicMock(
            return_value=[
                {"merged_at": None, "state": "closed"},
                {"merged_at": "2026-08-10T09:12:01Z", "state": "closed"},
            ]
        )

        assert client.branch_has_merged_pull_request("feature/SCRUM-16") is True
        client._request.assert_called_once_with(
            "GET",
            "/pulls",
            params={"state": "all", "head": "acme:feature/SCRUM-16"},
        )

    def test_false_when_no_pr_merged(self, client):
        client._request = MagicMock(
            return_value=[
                {"merged_at": None, "state": "open"},
                {"merged_at": None, "state": "closed"},
            ]
        )

        assert client.branch_has_merged_pull_request("feature/TICKET-1") is False

    def test_false_when_no_prs_at_all(self, client):
        client._request = MagicMock(return_value=[])
        assert client.branch_has_merged_pull_request("feature/TICKET-1") is False

    def test_false_on_api_error_fail_open(self, client):
        client._request = MagicMock(side_effect=GitHubAPIError(500, "Server error"))
        assert client.branch_has_merged_pull_request("feature/TICKET-1") is False


class TestResetBranchToBase:
    def test_force_updates_ref_to_base_tip(self, client):
        client._request = MagicMock(
            side_effect=[
                {"object": {"sha": "main-tip-sha"}},
                {"ref": "refs/heads/feature/TICKET-1"},
            ]
        )

        client.reset_branch_to_base("feature/TICKET-1")

        # Second call is the force-update PATCH to main's tip.
        patch_call = client._request.call_args_list[1]
        assert patch_call.args == ("PATCH", "/git/refs/heads/feature/TICKET-1")
        assert patch_call.kwargs["body"] == {"sha": "main-tip-sha", "force": True}

    def test_uses_custom_base_branch(self, client):
        client._request = MagicMock(
            side_effect=[
                {"object": {"sha": "develop-tip-sha"}},
                {"ref": "refs/heads/feature/TICKET-1"},
            ]
        )

        client.reset_branch_to_base("feature/TICKET-1", base_branch="develop")

        first_call = client._request.call_args_list[0]
        assert first_call.args == ("GET", "/git/ref/heads/develop")


class TestEnsureBranchDecidesResetVsSync:
    """
    The core fix for the feature/SCRUM-16 incident (PRs #15/#18/#20/#21):
    a branch whose PR was already merged must be reset fresh from main, not
    reused -- reusing it stacks new commits onto history main no longer
    wants (main reverted the merge), producing unresolvable conflicts.
    A branch that hasn't been merged yet is just synced with main instead.
    """

    def test_existing_branch_with_merged_pr_is_reset_not_synced(self, client):
        # GET /git/ref/heads/{branch} succeeds -> branch exists.
        client._request = MagicMock(return_value={"object": {"sha": "abc123"}})
        client.branch_has_merged_pull_request = MagicMock(return_value=True)
        client.reset_branch_to_base = MagicMock()
        client.sync_branch_with_base = MagicMock()

        result = client.ensure_branch("feature/SCRUM-16")

        client.reset_branch_to_base.assert_called_once_with("feature/SCRUM-16", "main")
        client.sync_branch_with_base.assert_not_called()
        assert result["action"] == "reset"
        assert result["conflict"] is False

    def test_existing_branch_without_merged_pr_is_synced(self, client):
        client._request = MagicMock(return_value={"object": {"sha": "abc123"}})
        client.branch_has_merged_pull_request = MagicMock(return_value=False)
        client.reset_branch_to_base = MagicMock()
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
        client.reset_branch_to_base.assert_not_called()
        assert result["action"] == "synced"
        assert result["synced"] is True

    def test_existing_branch_sync_conflict_is_surfaced(self, client):
        client._request = MagicMock(return_value={"object": {"sha": "abc123"}})
        client.branch_has_merged_pull_request = MagicMock(return_value=False)
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

    def test_new_branch_created_from_base_tip_no_merge_check_needed(self, client):
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
        client.branch_has_merged_pull_request = MagicMock()
        client.sync_branch_with_base = MagicMock()
        client.reset_branch_to_base = MagicMock()

        result = client.ensure_branch("feature/TICKET-1")

        # A newly created branch needs no merge check, sync, or reset.
        client.branch_has_merged_pull_request.assert_not_called()
        client.sync_branch_with_base.assert_not_called()
        client.reset_branch_to_base.assert_not_called()
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

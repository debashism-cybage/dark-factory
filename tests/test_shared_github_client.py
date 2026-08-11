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


class TestGetBranchHeadSha:
    def test_returns_sha_from_ref(self, client):
        client._request = MagicMock(return_value={"object": {"sha": "abc123"}})
        assert client.get_branch_head_sha("feature/TICKET-1") == "abc123"


class TestEnsurePullRequestDraft:
    def test_draft_flag_included_when_requested(self, client):
        client._request = MagicMock(
            side_effect=[
                [],  # no existing open PR
                {"number": 42, "html_url": "http://pr/42"},
            ]
        )

        result = client.ensure_pull_request(
            branch="feature/TICKET-1",
            ticket_id="TICKET-1",
            workflow_id="WF-1",
            draft=True,
        )

        assert result == {"number": 42, "url": "http://pr/42"}
        create_call = client._request.call_args_list[1]
        assert create_call.kwargs["body"]["draft"] is True

    def test_draft_flag_omitted_by_default(self, client):
        client._request = MagicMock(
            side_effect=[
                [],
                {"number": 43, "html_url": "http://pr/43"},
            ]
        )

        client.ensure_pull_request(branch="feature/TICKET-1", ticket_id="TICKET-1", workflow_id="WF-1")

        create_call = client._request.call_args_list[1]
        assert "draft" not in create_call.kwargs["body"]


class TestMarkPullRequestReady:
    def test_patches_draft_false(self, client):
        client._request = MagicMock(return_value={})
        client.mark_pull_request_ready(42)
        client._request.assert_called_once_with(
            "PATCH", "/pulls/42", body={"draft": False}
        )


class TestClosePullRequest:
    def test_closes_without_comment(self, client):
        client._request = MagicMock(return_value={})
        client.close_pull_request(42)
        client._request.assert_called_once_with(
            "PATCH", "/pulls/42", body={"state": "closed"}
        )

    def test_posts_comment_before_closing(self, client):
        client._request = MagicMock(return_value={})
        client.close_pull_request(42, comment="build never passed")

        calls = client._request.call_args_list
        assert calls[0].args == ("POST", "/issues/42/comments")
        assert calls[0].kwargs["body"] == {"body": "build never passed"}
        assert calls[1].args == ("PATCH", "/pulls/42")

    def test_comment_failure_does_not_block_close(self, client):
        # A failed comment post must not prevent the PR from still being
        # closed -- closing is the part that actually matters for the
        # build-gate policy (never leave a broken PR open).
        client._request = MagicMock(
            side_effect=[GitHubAPIError(500, "comment failed"), {}]
        )
        client.close_pull_request(42, comment="build never passed")
        assert client._request.call_count == 2


class TestGetWorkflowRunsForCommit:
    def test_returns_runs_sorted_by_run_number_desc(self, client):
        client._request = MagicMock(
            return_value={
                "workflow_runs": [
                    {"id": 1, "run_number": 1, "head_sha": "abc"},
                    {"id": 2, "run_number": 3, "head_sha": "abc"},
                    {"id": 3, "run_number": 2, "head_sha": "abc"},
                ]
            }
        )

        runs = client.get_workflow_runs_for_commit("abc", "pr-build-check.yml")

        assert [r["run_number"] for r in runs] == [3, 2, 1]

    def test_returns_empty_on_api_error(self, client):
        client._request = MagicMock(side_effect=GitHubAPIError(404, "not found"))
        assert client.get_workflow_runs_for_commit("abc", "pr-build-check.yml") == []

    def test_returns_empty_when_no_runs(self, client):
        client._request = MagicMock(return_value={"workflow_runs": []})
        assert client.get_workflow_runs_for_commit("abc", "pr-build-check.yml") == []


class TestWaitForCiBuild:
    def _make_client_with_runs(self, client, run_sequences):
        """run_sequences: list of lists of run dicts, one list per poll."""
        client.get_workflow_runs_for_commit = MagicMock(side_effect=run_sequences)
        return client

    def test_returns_success_immediately_when_run_already_completed(self, client):
        self._make_client_with_runs(
            client,
            [[{"id": 1, "status": "completed", "conclusion": "success", "html_url": "http://run/1"}]],
        )

        result = client.wait_for_ci_build(
            commit_sha="abc",
            workflow_file="pr-build-check.yml",
            sleep_fn=MagicMock(),
        )

        assert result == {"outcome": "SUCCESS", "runUrl": "http://run/1", "runId": 1, "conclusion": "success"}

    def test_returns_failure_on_non_success_conclusion(self, client):
        self._make_client_with_runs(
            client,
            [[{"id": 1, "status": "completed", "conclusion": "failure", "html_url": "http://run/1"}]],
        )

        result = client.wait_for_ci_build(
            commit_sha="abc",
            workflow_file="pr-build-check.yml",
            sleep_fn=MagicMock(),
        )

        assert result["outcome"] == "FAILURE"

    def test_polls_until_run_completes(self, client):
        self._make_client_with_runs(
            client,
            [
                [{"id": 1, "status": "in_progress", "conclusion": None, "html_url": "http://run/1"}],
                [{"id": 1, "status": "in_progress", "conclusion": None, "html_url": "http://run/1"}],
                [{"id": 1, "status": "completed", "conclusion": "success", "html_url": "http://run/1"}],
            ],
        )
        sleep_fn = MagicMock()
        now_values = iter([0, 1, 2, 3])
        now_fn = MagicMock(side_effect=lambda: next(now_values))

        result = client.wait_for_ci_build(
            commit_sha="abc",
            workflow_file="pr-build-check.yml",
            timeout_seconds=100,
            sleep_fn=sleep_fn,
            now_fn=now_fn,
        )

        assert result["outcome"] == "SUCCESS"
        assert sleep_fn.call_count == 2

    def test_times_out_when_run_never_completes(self, client):
        self._make_client_with_runs(
            client,
            [
                [{"id": 1, "status": "in_progress", "conclusion": None, "html_url": "http://run/1"}]
                for _ in range(20)
            ],
        )
        sleep_fn = MagicMock()
        # now_fn: first call establishes the deadline baseline, subsequent
        # calls all report past the deadline immediately.
        now_values = iter([0] + [1000] * 20)
        now_fn = MagicMock(side_effect=lambda: next(now_values))

        result = client.wait_for_ci_build(
            commit_sha="abc",
            workflow_file="pr-build-check.yml",
            timeout_seconds=10,
            sleep_fn=sleep_fn,
            now_fn=now_fn,
        )

        assert result["outcome"] == "TIMEOUT"

    def test_not_found_when_no_run_ever_appears(self, client):
        self._make_client_with_runs(client, [[] for _ in range(20)])
        sleep_fn = MagicMock()
        now_values = iter([0] + [1000] * 20)
        now_fn = MagicMock(side_effect=lambda: next(now_values))

        result = client.wait_for_ci_build(
            commit_sha="abc",
            workflow_file="pr-build-check.yml",
            timeout_seconds=10,
            sleep_fn=sleep_fn,
            now_fn=now_fn,
        )

        assert result["outcome"] == "NOT_FOUND"
        assert result["runUrl"] is None


class TestGetRunJobsAndLogs:
    def test_get_run_jobs_returns_list(self, client):
        client._request = MagicMock(return_value={"jobs": [{"id": 1, "conclusion": "failure"}]})
        jobs = client.get_run_jobs(123)
        assert jobs == [{"id": 1, "conclusion": "failure"}]

    def test_get_run_jobs_returns_empty_on_error(self, client):
        client._request = MagicMock(side_effect=GitHubAPIError(404, "not found"))
        assert client.get_run_jobs(123) == []

    def test_get_failed_job_log_text_finds_failed_job(self, client):
        client.get_run_jobs = MagicMock(
            return_value=[
                {"id": 1, "conclusion": "success"},
                {"id": 2, "conclusion": "failure"},
            ]
        )
        client.get_job_log_text = MagicMock(return_value="log text here")

        result = client.get_failed_job_log_text(999)

        assert result == "log text here"
        client.get_job_log_text.assert_called_once_with(2)

    def test_get_failed_job_log_text_returns_none_when_no_failed_job(self, client):
        client.get_run_jobs = MagicMock(return_value=[{"id": 1, "conclusion": "success"}])
        client.get_job_log_text = MagicMock()

        result = client.get_failed_job_log_text(999)

        assert result is None
        client.get_job_log_text.assert_not_called()

"""
Tests for the Development Agent handler's build-fix routing and self-review
failure handling.

Focus areas:
1. The MISSING_MODULE fix path added to close the SCRUM-10 gap, where
   `_attempt_build_fix` could only ever patch the *importing* file and had
   no way to create a dependency that was never planned or generated.
2. The parent-vs-child misattribution bug (also SCRUM-10/SCRUM-14): build
   validation correctly detected "not integrated into any parent" but
   reported the child file instead of the parent that needed the fix.
3. The silent-skip-on-review-failure bug (SCRUM-10/SCRUM-14 root cause):
   when self-review failed twice (e.g. truncated generation), the file was
   silently skipped and the PR was opened anyway with the original
   placeholder untouched. This must now abort the workflow instead.
"""

from unittest.mock import MagicMock, patch

from agents.development.handler import (
    _attempt_build_fix,
    _attempt_create_missing_module,
    _redirect_integration_issue_to_parent,
    _run_ci_build_gate,
    lambda_handler,
)


class TestLambdaHandlerAbortsOnUnrecoverableReviewFailure:
    """
    Reproduces the SCRUM-10/SCRUM-14 root cause end-to-end: the hub page
    file (the one that wires the API/service/child component together)
    fails self-review twice in a row (e.g. truncated generation) and must
    now cause the workflow to abort with no PR created — not silently ship
    a PR containing the untouched original placeholder.
    """

    def _event(self):
        return {
            "workflowId": "WF-TEST",
            "ticketId": "SCRUM-99",
            "summary": "Implement Widgets Dashboard using API",
            "planning": {
                "implementationContract": {
                    "files": [
                        {
                            "path": "src/app/widgets/widgets.ts",
                            "operation": "MODIFY",
                            "expectedChanges": ["Fetch and display widgets from the API"],
                            "sha256": None,
                        }
                    ],
                    "protectedFiles": [],
                    "validationChecklist": [],
                }
            },
        }

    @patch("agents.development.handler.S3Helper")
    @patch("agents.development.handler.WorkflowTable")
    @patch("agents.development.handler.BedrockClient")
    @patch("agents.development.handler.GitHubClient")
    @patch("agents.development.handler.DevelopmentConfig")
    @patch("agents.development.handler._self_review")
    def test_aborts_without_creating_pr_when_review_fails_after_all_retries(
        self,
        mock_self_review,
        mock_config_cls,
        mock_github_cls,
        mock_bedrock_cls,
        mock_table_cls,
        mock_s3_cls,
    ):
        mock_config_cls.return_value = MagicMock(
            github_repo_owner="owner",
            github_repo_name="repo",
            github_secret_name="secret",
            bedrock_model_id="model",
            bucket_name="bucket",
            table_name="table",
        )

        github = mock_github_cls.return_value
        github.ensure_branch.return_value = None
        github.get_file_content.return_value = "export class WidgetsComponent {}"

        bedrock = mock_bedrock_cls.return_value
        bedrock.converse.return_value = "export class WidgetsComponent { /* truncated"

        # Every self-review call fails, simulating persistent truncation.
        mock_self_review.return_value = "FAIL: generated code is truncated/incomplete"

        result = lambda_handler(self._event(), context=None)

        assert result["status"] == "DEVELOPMENT_ABORTED"
        assert "REVIEW_FAILED_UNRECOVERABLE" in result["artifacts"]["reason"]
        # No PR should ever be created for an unimplemented hub file.
        github.ensure_pull_request.assert_not_called()

    @patch("agents.development.handler.S3Helper")
    @patch("agents.development.handler.WorkflowTable")
    @patch("agents.development.handler.BedrockClient")
    @patch("agents.development.handler.GitHubClient")
    @patch("agents.development.handler.DevelopmentConfig")
    @patch("agents.development.handler._self_review")
    def test_retry_prompt_includes_previous_failure_reason(
        self,
        mock_self_review,
        mock_config_cls,
        mock_github_cls,
        mock_bedrock_cls,
        mock_table_cls,
        mock_s3_cls,
    ):
        # First review fails, second (retry) passes. The retry's user_prompt
        # sent to Bedrock must reference the specific failure reason, not
        # just re-send the identical original prompt (which reproduces the
        # identical failure, as happened on SCRUM-10/SCRUM-14).
        mock_config_cls.return_value = MagicMock(
            github_repo_owner="owner",
            github_repo_name="repo",
            github_secret_name="secret",
            bedrock_model_id="model",
            bucket_name="bucket",
            table_name="table",
        )

        github = mock_github_cls.return_value
        github.ensure_branch.return_value = None
        github.get_file_content.return_value = "export class WidgetsComponent {}"
        github.ensure_pull_request.return_value = {"number": 1, "url": "http://pr/1"}
        github.get_branch_head_sha.return_value = "abc123"
        # Mandatory CI build gate: simulate the real GitHub Actions build
        # passing on the first poll, so this test can focus purely on the
        # self-review retry-with-feedback behavior it's actually testing.
        github.wait_for_ci_build.return_value = {
            "outcome": "SUCCESS",
            "runUrl": "http://run/1",
            "runId": 1,
            "conclusion": "success",
        }

        bedrock = mock_bedrock_cls.return_value
        bedrock.converse.return_value = "export class WidgetsComponent {}"

        mock_self_review.side_effect = [
            "FAIL: generated code is truncated/incomplete",
            "PASS",
        ]

        result = lambda_handler(self._event(), context=None)

        assert result["status"] == "DEVELOPMENT_COMPLETE"
        # Second call to bedrock.converse is the retry — check it references
        # the failure reason so the model gets specific corrective feedback.
        retry_call_kwargs = bedrock.converse.call_args_list[1].kwargs
        assert "truncated/incomplete" in retry_call_kwargs["user_prompt"]
        assert "PREVIOUS ATTEMPT REJECTED" in retry_call_kwargs["user_prompt"]


class TestRunCiBuildGate:
    """
    Tests for the mandatory, non-negotiable PR build gate: a PR may only be
    created after the repository's REAL `npx ng build` CI run (not a
    re-implementation of it — this Lambda has no Node/Angular toolchain)
    reports success for the exact commit being shipped.
    """

    def _event(self):
        return {"workflowId": "WF-TEST", "ticketId": "SCRUM-99"}

    def test_passes_immediately_on_first_green_ci_run(self):
        bedrock = MagicMock()
        github = MagicMock()
        github.get_branch_head_sha.return_value = "sha1"
        github.ensure_pull_request.return_value = {"number": 5, "url": "http://pr/5"}
        github.wait_for_ci_build.return_value = {
            "outcome": "SUCCESS",
            "runUrl": "http://run/1",
            "runId": 1,
            "conclusion": "success",
        }
        config = MagicMock(ci_build_workflow_file="pr-build-check.yml")

        result = _run_ci_build_gate(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-99",
            event=self._event(),
            ticket_id="SCRUM-99",
            contract_files=[],
            validation_checklist=[],
            generated_files=[],
            config=config,
        )

        assert result["passed"] is True
        assert result["prNumber"] == 5
        github.ensure_pull_request.assert_called_once()
        assert github.ensure_pull_request.call_args.kwargs["draft"] is True
        github.close_pull_request.assert_not_called()

    def test_opens_pr_as_draft_exactly_once_across_fix_rounds(self):
        # A fresh draft PR must not be re-opened on every retry round -- the
        # SAME PR should be polled, fixed against, and eventually promoted.
        bedrock = MagicMock()
        bedrock.converse.return_value = "export class Fixed {}"
        github = MagicMock()
        github.get_branch_head_sha.return_value = "sha1"
        github.ensure_pull_request.return_value = {"number": 7, "url": "http://pr/7"}
        github.wait_for_ci_build.side_effect = [
            {"outcome": "FAILURE", "runUrl": "http://run/1", "runId": 1, "conclusion": "failure"},
            {"outcome": "SUCCESS", "runUrl": "http://run/2", "runId": 2, "conclusion": "success"},
        ]
        github.get_failed_job_log_text.return_value = (
            "\u2718 [ERROR] TS2339: Property 'x' does not exist on type 'Y'. [plugin angular-compiler]\n"
            "\n"
            "    src/app/a.ts:1:1:\n"
            "      1 \u2502 x\n"
        )
        config = MagicMock(ci_build_workflow_file="pr-build-check.yml")

        result = _run_ci_build_gate(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-99",
            event=self._event(),
            ticket_id="SCRUM-99",
            contract_files=[],
            validation_checklist=[],
            generated_files=[],
            config=config,
        )

        assert result["passed"] is True
        github.ensure_pull_request.assert_called_once()

    def test_closes_draft_pr_and_reports_failure_after_exhausting_fix_rounds(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = "export class StillBroken {}"
        github = MagicMock()
        github.get_branch_head_sha.return_value = "sha1"
        github.ensure_pull_request.return_value = {"number": 9, "url": "http://pr/9"}
        github.wait_for_ci_build.return_value = {
            "outcome": "FAILURE",
            "runUrl": "http://run/1",
            "runId": 1,
            "conclusion": "failure",
        }
        github.get_failed_job_log_text.return_value = (
            "\u2718 [ERROR] TS2339: Property 'x' does not exist on type 'Y'. [plugin angular-compiler]\n"
            "\n"
            "    src/app/a.ts:1:1:\n"
            "      1 \u2502 x\n"
        )
        config = MagicMock(ci_build_workflow_file="pr-build-check.yml")

        result = _run_ci_build_gate(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-99",
            event=self._event(),
            ticket_id="SCRUM-99",
            contract_files=[],
            validation_checklist=[],
            generated_files=[],
            config=config,
        )

        assert result["passed"] is False
        assert result["buildErrors"]
        # PR must be closed -- never left open, draft or otherwise, in a
        # state that never passed the real build.
        github.close_pull_request.assert_called_once()
        assert github.close_pull_request.call_args.args[0] == 9

    def test_never_opens_a_pr_if_ci_never_confirms_a_result(self):
        # TIMEOUT/NOT_FOUND on every attempt -- can't confirm PR_READY, so
        # the gate must still fail closed rather than assume success.
        bedrock = MagicMock()
        github = MagicMock()
        github.get_branch_head_sha.return_value = "sha1"
        github.ensure_pull_request.return_value = {"number": 3, "url": "http://pr/3"}
        github.wait_for_ci_build.return_value = {
            "outcome": "NOT_FOUND",
            "runUrl": None,
            "runId": None,
            "conclusion": None,
        }
        config = MagicMock(ci_build_workflow_file="pr-build-check.yml")

        result = _run_ci_build_gate(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-99",
            event=self._event(),
            ticket_id="SCRUM-99",
            contract_files=[],
            validation_checklist=[],
            generated_files=[],
            config=config,
        )

        assert result["passed"] is False
        github.close_pull_request.assert_called_once()

    def test_missing_module_error_from_ci_routes_to_create_not_patch(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = "export class MissingThing {}"
        github = MagicMock()
        github.get_branch_head_sha.return_value = "sha1"
        github.ensure_pull_request.return_value = {"number": 11, "url": "http://pr/11"}
        github.file_exists.return_value = False
        github.get_file_content.return_value = (
            "import { MissingThing } from './missing-thing';"
        )
        github.wait_for_ci_build.side_effect = [
            {"outcome": "FAILURE", "runUrl": "http://run/1", "runId": 1, "conclusion": "failure"},
            {"outcome": "SUCCESS", "runUrl": "http://run/2", "runId": 2, "conclusion": "success"},
        ]
        github.get_failed_job_log_text.return_value = (
            "\u2718 [ERROR] TS2307: Cannot find module './missing-thing' or its "
            "corresponding type declarations. [plugin angular-compiler]\n"
            "\n"
            "    src/app/uses-it.ts:1:26:\n"
            "      1 \u2502 import { MissingThing } from './missing-thing';\n"
        )
        config = MagicMock(ci_build_workflow_file="pr-build-check.yml")

        result = _run_ci_build_gate(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-99",
            event=self._event(),
            ticket_id="SCRUM-99",
            contract_files=[],
            validation_checklist=[],
            generated_files=[],
            config=config,
        )

        assert result["passed"] is True
        # The missing file must be CREATED, not the importer patched.
        commit_kwargs = github.commit_file.call_args.kwargs
        assert commit_kwargs["path"] == "src/app/missing-thing.ts"


class TestAttemptCreateMissingModule:
    def _issue(self, **overrides):
        issue = {
            "file": "src/app/recipes/recipes.ts",
            "issue": "Cannot find module './recipe-card/recipe-card'",
            "fix": "Update the import path to point to a file that exists.",
            "kind": "MISSING_MODULE",
            "expectedPath": "src/app/recipes/recipe-card/recipe-card.ts",
            "requiredExports": ["RecipeCardComponent"],
            "importingModule": "./recipe-card/recipe-card",
        }
        issue.update(overrides)
        return issue

    def test_creates_missing_file_and_returns_success_entry(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = "export class RecipeCardComponent {}"

        github = MagicMock()
        github.file_exists.return_value = False
        github.get_file_content.return_value = (
            "import { RecipeCardComponent } from './recipe-card/recipe-card';"
        )

        result = _attempt_create_missing_module(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-10",
            event={"ticketId": "SCRUM-10"},
            issue=self._issue(),
            ticket_id="SCRUM-10",
            validation_checklist=[],
        )

        assert result is not None
        assert result["path"] == "src/app/recipes/recipe-card/recipe-card.ts"
        assert result["operation"] == "BUILD_FIX"
        assert result["status"] == "SUCCESS"

        # The missing file itself must be committed, not the importer.
        github.commit_file.assert_called_once()
        commit_kwargs = github.commit_file.call_args.kwargs
        assert commit_kwargs["path"] == "src/app/recipes/recipe-card/recipe-card.ts"
        assert commit_kwargs["branch"] == "feature/SCRUM-10"

    def test_skips_if_target_already_exists(self):
        # If a previous fix round already created the file, don't overwrite
        # it blindly on stale issue data — let re-validation judge it.
        bedrock = MagicMock()
        github = MagicMock()
        github.file_exists.return_value = True

        result = _attempt_create_missing_module(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-10",
            event={"ticketId": "SCRUM-10"},
            issue=self._issue(),
            ticket_id="SCRUM-10",
            validation_checklist=[],
        )

        assert result is None
        github.commit_file.assert_not_called()
        bedrock.converse.assert_not_called()

    def test_returns_none_when_missing_required_fields(self):
        bedrock = MagicMock()
        github = MagicMock()

        result = _attempt_create_missing_module(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-10",
            event={},
            issue={"file": "", "expectedPath": ""},
            ticket_id="SCRUM-10",
            validation_checklist=[],
        )

        assert result is None

    def test_bedrock_failure_returns_none(self):
        bedrock = MagicMock()
        bedrock.converse.side_effect = RuntimeError("boom")

        github = MagicMock()
        github.file_exists.return_value = False
        github.get_file_content.return_value = "irrelevant"

        result = _attempt_create_missing_module(
            bedrock=bedrock,
            github=github,
            branch="feature/SCRUM-10",
            event={},
            issue=self._issue(),
            ticket_id="SCRUM-10",
            validation_checklist=[],
        )

        assert result is None


class TestRedirectIntegrationIssueToParent:
    """
    Tests for the SCRUM-10/SCRUM-14 misattribution bug: build validation
    correctly detected "component/service created but not integrated into
    any parent", but the LLM reported the CHILD file as the fix target
    instead of the PARENT that actually needed the import/injection added.
    This caused three rounds of fixes to repeatedly regenerate an
    already-correct child component while the real broken parent (the page
    that should call the service and render the child) was never touched.
    """

    def _contract_files(self):
        return [
            {
                "path": "src/app/recipes/recipe-card/recipe-card.ts",
                "operation": "CREATE",
                "integratesWith": ["src/app/recipes/recipes.ts"],
            },
            {
                "path": "src/app/services/recipes.service.ts",
                "operation": "CREATE",
                "integratesWith": ["src/app/recipes/recipes.ts"],
            },
            {
                "path": "src/app/recipes/recipes.ts",
                "operation": "MODIFY",
                "integratesWith": [],
            },
        ]

    def test_redirects_child_component_issue_to_declared_parent(self):
        issue = {
            "file": "src/app/recipes/recipe-card/recipe-card.ts",
            "issue": (
                "component created but not integrated into any parent — "
                "RecipesComponent does not import RecipeCardComponent"
            ),
            "fix": "add <app-recipe-card> to the parent template",
        }

        result = _redirect_integration_issue_to_parent(issue, self._contract_files())

        assert result["file"] == "src/app/recipes/recipes.ts"

    def test_redirects_child_service_issue_to_declared_parent(self):
        issue = {
            "file": "src/app/services/recipes.service.ts",
            "issue": "RecipesService is created but never injected or used in any component shown",
            "fix": "inject RecipesService into RecipesComponent",
        }

        result = _redirect_integration_issue_to_parent(issue, self._contract_files())

        assert result["file"] == "src/app/recipes/recipes.ts"

    def test_leaves_non_integration_issue_unchanged(self):
        issue = {
            "file": "src/app/recipes/recipe-card/recipe-card.ts",
            "issue": "Property 'bar' does not exist on type 'Recipe'",
            "fix": "use an existing member",
        }

        result = _redirect_integration_issue_to_parent(issue, self._contract_files())

        assert result["file"] == "src/app/recipes/recipe-card/recipe-card.ts"

    def test_leaves_issue_unchanged_when_no_parent_declared(self):
        issue = {
            "file": "src/app/utils/helper.ts",
            "issue": "helper created but not integrated into any parent",
            "fix": "use it somewhere",
        }
        contract_files = [
            {"path": "src/app/utils/helper.ts", "operation": "CREATE", "integratesWith": []},
        ]

        result = _redirect_integration_issue_to_parent(issue, contract_files)

        assert result["file"] == "src/app/utils/helper.ts"

    def test_leaves_issue_unchanged_when_file_already_is_parent(self):
        # If the LLM already correctly reported the parent (a MODIFY entry,
        # not a CREATE entry), there's nothing to redirect.
        issue = {
            "file": "src/app/recipes/recipes.ts",
            "issue": "service created but not integrated into any parent",
            "fix": "inject the service",
        }

        result = _redirect_integration_issue_to_parent(issue, self._contract_files())

        assert result["file"] == "src/app/recipes/recipes.ts"


class TestAttemptBuildFixStillPatchesNonMissingModuleIssues:
    def test_patches_importer_for_non_missing_module_issue(self):
        # Existing behavior must be preserved for issue kinds that ARE
        # fixable by patching the file in place (e.g. wrong member access).
        bedrock = MagicMock()
        bedrock.converse.return_value = "export class Foo {}"

        github = MagicMock()
        github.get_file_content.return_value = "export class FooOld {}"

        issue = {
            "file": "src/app/foo.ts",
            "issue": "Property 'bar' does not exist on type 'Foo'",
            "fix": "Use an existing member.",
        }

        result = _attempt_build_fix(
            bedrock=bedrock,
            github=github,
            branch="feature/TEST-1",
            event={},
            issue=issue,
            ticket_id="TEST-1",
            validation_checklist=[],
        )

        assert result is not None
        assert result["path"] == "src/app/foo.ts"
        github.commit_file.assert_called_once()

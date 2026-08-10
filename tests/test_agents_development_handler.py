"""
Tests for the Development Agent handler's build-fix routing.

Focus: the MISSING_MODULE fix path added to close the SCRUM-10 gap, where
`_attempt_build_fix` could only ever patch the *importing* file and had no
way to create a dependency that was never planned or generated. Two prior
auto-fix commits on that ticket just toggled the broken import path between
two equally-nonexistent files because of this gap.
"""

from unittest.mock import MagicMock

from agents.development.handler import (
    _attempt_build_fix,
    _attempt_create_missing_module,
)


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

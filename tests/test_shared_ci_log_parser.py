"""
Tests for shared.ci_log_parser — extracting structured compiler errors from
raw GitHub Actions job log text for the mandatory CI build gate.

Fixtures reproduce the exact log shapes reported in this session (PR #33,
PR #35), with GitHub Actions' per-line ISO-8601 timestamp prefixes, which
the real `get_job_log_text` download includes and this parser must strip.
"""

from shared.ci_log_parser import parse_ng_build_errors


def _with_timestamps(raw: str) -> str:
    """Simulate GitHub Actions' per-line timestamp prefix on raw log text."""
    ts = "2026-08-10T15:11:04.3960000Z"
    return "\n".join(f"{ts} {line}" if line else ts for line in raw.split("\n"))


class TestParseNgBuildErrors:
    def test_empty_log_returns_empty(self):
        assert parse_ng_build_errors("") == []
        assert parse_ng_build_errors(None) == []  # type: ignore[arg-type]

    def test_single_error_ts2339(self):
        # Reproduces PR #33's exact reported error.
        raw = (
            "Run npx ng build --configuration production --base-href /angular-dev/\n"
            "\u2718 [ERROR] TS2339: Property 'description' does not exist on type 'Exercise'. [plugin angular-compiler]\n"
            "\n"
            "    src/app/exercises/exercise-card/exercise-card.component.ts:12:20:\n"
            "      12 \u2502       @if (exercise.description) {\n"
            "         \u2575                     ~~~~~~~~~~~\n"
        )
        log_text = _with_timestamps(raw)

        issues = parse_ng_build_errors(log_text)

        assert len(issues) == 1
        assert issues[0]["file"] == "src/app/exercises/exercise-card/exercise-card.component.ts"
        assert "TS2339" in issues[0]["issue"]
        assert "description" in issues[0]["issue"]
        assert "line 12" in issues[0]["issue"]

    def test_multiple_errors_same_log(self):
        # Reproduces PR #35's exact reported errors (hasNextPage/nextCursor
        # x2 each, plus the duplicate-Exercise TS2741).
        raw = (
            "\u2718 [ERROR] TS2339: Property 'hasNextPage' does not exist on type 'ExercisesResponse'. [plugin angular-compiler]\n"
            "\n"
            "    src/app/exercises/exercises.ts:125:38:\n"
            "      125 \u2502         this.hasNextPage.set(response.hasNextPage);\n"
            "          \u2575                                       ~~~~~~~~~~\n"
            "\n"
            "\u2718 [ERROR] TS2339: Property 'nextCursor' does not exist on type 'ExercisesResponse'. [plugin angular-compiler]\n"
            "\n"
            "    src/app/exercises/exercises.ts:126:37:\n"
            "      126 \u2502         this.nextCursor.set(response.nextCursor ?? null);\n"
            "          \u2575                                      ~~~~~~~~~~\n"
        )
        log_text = _with_timestamps(raw)

        issues = parse_ng_build_errors(log_text)

        assert len(issues) == 2
        assert {i["issue"].split(":")[0].strip() or "TS2339" for i in issues}
        assert any("hasNextPage" in i["issue"] and "line 125" in i["issue"] for i in issues)
        assert any("nextCursor" in i["issue"] and "line 126" in i["issue"] for i in issues)
        assert all(i["file"] == "src/app/exercises/exercises.ts" for i in issues)

    def test_cannot_find_module_marked_as_missing_module(self):
        raw = (
            "\u2718 [ERROR] TS2307: Cannot find module './auth/auth.guard' or its corresponding type declarations. [plugin angular-compiler]\n"
            "\n"
            "    src/app/app.routes.ts:2:26:\n"
            "      2 \u2502 import { authGuard } from './auth/auth.guard';\n"
            "        \u2575                          ~~~~~~~~~~~~~~~~~~~~\n"
        )
        log_text = _with_timestamps(raw)

        issues = parse_ng_build_errors(log_text)

        assert len(issues) == 1
        assert issues[0]["kind"] == "MISSING_MODULE"
        assert issues[0]["importingModule"] == "./auth/auth.guard"

    def test_duplicate_errors_deduplicated(self):
        raw = (
            "\u2718 [ERROR] TS2339: Property 'x' does not exist on type 'Y'. [plugin angular-compiler]\n"
            "\n"
            "    src/app/a.ts:1:1:\n"
            "      1 \u2502 x\n"
        )
        log_text = _with_timestamps(raw + raw)  # same error appears twice

        issues = parse_ng_build_errors(log_text)
        assert len(issues) == 1

    def test_non_compiler_log_returns_empty(self):
        raw = "npm ERR! network timeout\nnpm ERR! could not resolve host\n"
        log_text = _with_timestamps(raw)
        assert parse_ng_build_errors(log_text) == []

    def test_strips_ansi_color_codes(self):
        raw = (
            "\x1b[31m\u2718 [ERROR]\x1b[0m TS2339: Property 'x' does not exist on type 'Y'. [plugin angular-compiler]\n"
            "\n"
            "    src/app/a.ts:5:10:\n"
            "      5 \u2502 x\n"
        )
        log_text = _with_timestamps(raw)

        issues = parse_ng_build_errors(log_text)
        assert len(issues) == 1
        assert issues[0]["file"] == "src/app/a.ts"

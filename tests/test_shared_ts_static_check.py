"""
Tests for shared.ts_static_check — the deterministic TS/Angular checker.

These reproduce the exact real-world compiler errors that motivated this
module (see agents/development/handler.py docstring):
    TS2307 Cannot find module '...'
    TS2339 Property 'X' does not exist on type '...'
    TS2551 Property 'X' does not exist on type '...'. Did you mean 'Y'?
"""

from shared.ts_static_check import (
    check_typescript_integrity,
    extract_class_members,
    extract_exports,
    extract_injected_services,
    parse_dynamic_then_imports,
    parse_static_imports,
    resolve_module_path,
)


class TestParseStaticImports:
    def test_named_import(self):
        content = "import { authGuard } from './auth/auth.guard';"
        result = parse_static_imports(content)
        assert result[0]["module"] == "./auth/auth.guard"
        assert result[0]["named"] == [("authGuard", "authGuard")]

    def test_named_import_with_alias(self):
        content = "import { Foo as Bar } from './foo';"
        result = parse_static_imports(content)
        assert result[0]["named"] == [("Bar", "Foo")]

    def test_default_import(self):
        content = "import Foo from './foo';"
        result = parse_static_imports(content)
        assert result[0]["default"] == "Foo"

    def test_package_import_still_parsed(self):
        content = "import { Injectable } from '@angular/core';"
        result = parse_static_imports(content)
        assert result[0]["module"] == "@angular/core"


class TestParseDynamicThenImports:
    def test_lazy_route_component(self):
        content = "component: () => import('./recipes/recipes').then((m) => m.Recipes),"
        result = parse_dynamic_then_imports(content)
        assert result == [{"module": "./recipes/recipes", "member": "Recipes"}]

    def test_multiple_routes(self):
        content = """
        component: () => import('./products/products').then((m) => m.Products),
        component: () => import('./exercises/exercises').then((m) => m.Exercises),
        """
        result = parse_dynamic_then_imports(content)
        assert {r["member"] for r in result} == {"Products", "Exercises"}


class TestExtractExports:
    def test_export_class(self):
        content = "export class RecipesComponent {}"
        assert "RecipesComponent" in extract_exports(content)

    def test_export_const_function(self):
        content = "export const authGuard: CanActivateFn = () => true;"
        assert "authGuard" in extract_exports(content)

    def test_export_brace(self):
        content = "class Foo {}\nexport { Foo };"
        assert "Foo" in extract_exports(content)

    def test_no_matching_export(self):
        # File exports 'RecipesComponent' but NOT 'Recipes' — this is the
        # exact real-world bug: import expects 'Recipes', file has
        # 'RecipesComponent'.
        content = "export class RecipesComponent {}"
        exports = extract_exports(content)
        assert "Recipes" not in exports


class TestResolveModulePath:
    def test_resolves_ts_extension(self):
        known = {"src/app/auth/auth.guard.ts"}
        resolved = resolve_module_path("src/app/app.routes.ts", "./auth/auth.guard", known)
        assert resolved == "src/app/auth/auth.guard.ts"

    def test_unresolvable_path_returns_none(self):
        known = {"src/app/guards/auth.guard.ts"}  # different directory
        resolved = resolve_module_path("src/app/app.routes.ts", "./auth/auth.guard", known)
        assert resolved is None

    def test_package_import_returns_none(self):
        resolved = resolve_module_path("src/app/app.routes.ts", "@angular/core", set())
        assert resolved is None

    def test_resolves_index_file(self):
        known = {"src/app/utils/index.ts"}
        resolved = resolve_module_path("src/app/app.component.ts", "./utils", known)
        assert resolved == "src/app/utils/index.ts"


class TestExtractInjectedServices:
    def test_constructor_param(self):
        content = """
        constructor(private authService: AuthService, private router: Router) {}
        """
        services = extract_injected_services(content)
        assert services == {"authService": "AuthService", "router": "Router"}

    def test_inject_function(self):
        content = "private authService = inject(AuthService);"
        services = extract_injected_services(content)
        assert services["authService"] == "AuthService"


class TestExtractClassMembers:
    def test_finds_property(self):
        content = """
        export class AuthService {
            readonly isLoading = this.loading.asReadonly();
        }
        """
        members = extract_class_members(content, "AuthService")
        assert members is not None
        assert "isLoading" in members

    def test_missing_member_not_present(self):
        # The exact real-world bug: code accesses `.loading$` but the class
        # only declares `isLoading`.
        content = """
        export class AuthService {
            readonly isLoading = this.loading.asReadonly();
        }
        """
        members = extract_class_members(content, "AuthService")
        assert members is not None
        assert "loading$" not in members

    def test_finds_method(self):
        content = """
        export class AuthService {
            login(username: string, password: string): Observable<boolean> {
                return this.http.post('/login', { username, password });
            }
        }
        """
        members = extract_class_members(content, "AuthService")
        assert members is not None
        assert "login" in members

    def test_class_not_found_returns_none(self):
        content = "export class SomethingElse {}"
        assert extract_class_members(content, "AuthService") is None


class TestCheckTypescriptIntegrityRealWorldBugs:
    """
    End-to-end reproductions of the reported build failures, run through
    check_typescript_integrity exactly as the Development Agent would.
    """

    def test_unresolvable_relative_import_ts2307(self):
        routes_content = "import { authGuard } from './auth/auth.guard';\nexport const routes = [];"
        files = {"src/app/app.routes.ts": routes_content}
        # Real file lives at guards/auth.guard.ts, not auth/auth.guard.ts
        known_paths = {"src/app/app.routes.ts", "src/app/guards/auth.guard.ts"}

        issues = check_typescript_integrity(files, known_paths, fetch_content=lambda p: None)

        assert len(issues) == 1
        assert issues[0]["file"] == "src/app/app.routes.ts"
        assert "auth/auth.guard" in issues[0]["issue"]

    def test_dynamic_import_wrong_export_name_ts2339(self):
        routes_content = "component: () => import('./recipes/recipes').then((m) => m.Recipes),"
        files = {"src/app/app.routes.ts": routes_content}
        known_paths = {"src/app/app.routes.ts", "src/app/recipes/recipes.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/recipes/recipes.ts":
                return "export class RecipesComponent {}"
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)

        assert len(issues) == 1
        assert "Recipes" in issues[0]["issue"]
        assert "RecipesComponent" in issues[0]["fix"]

    def test_property_does_not_exist_on_service_ts2551(self):
        guard_content = """
        import { AuthService } from '../services/auth.service';
        export const authGuard = () => {
            const authService = inject(AuthService);
            return authService.loading$.pipe();
        };
        """
        files = {"src/app/guards/auth.guard.ts": guard_content}
        known_paths = {"src/app/guards/auth.guard.ts", "src/app/services/auth.service.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/services/auth.service.ts":
                return """
                export class AuthService {
                    readonly isLoading = this.loading.asReadonly();
                }
                """
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)

        assert len(issues) == 1
        assert "loading$" in issues[0]["issue"]
        assert "isLoading" in issues[0]["issue"]  # "Did you mean" suggestion

    def test_correct_code_produces_no_issues(self):
        routes_content = "import { authGuard } from './guards/auth.guard';\nexport const routes = [];"
        files = {"src/app/app.routes.ts": routes_content}
        known_paths = {"src/app/app.routes.ts", "src/app/guards/auth.guard.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/guards/auth.guard.ts":
                return "export const authGuard = () => true;"
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert issues == []

    def test_package_imports_are_not_flagged(self):
        content = "import { Injectable } from '@angular/core';\nimport { Observable } from 'rxjs';"
        files = {"src/app/services/auth.service.ts": content}
        known_paths = {"src/app/services/auth.service.ts"}

        issues = check_typescript_integrity(files, known_paths, fetch_content=lambda p: None)
        assert issues == []

    def test_newly_created_sibling_file_in_same_changeset_resolves(self):
        # Both files are part of the same changeset (not yet on disk from
        # the checker's fetch_content perspective) — known_paths must
        # include them so cross-references within one changeset resolve.
        guard_content = "export const authGuard = () => true;"
        routes_content = "import { authGuard } from './guards/auth.guard';"
        files = {
            "src/app/guards/auth.guard.ts": guard_content,
            "src/app/app.routes.ts": routes_content,
        }
        known_paths = set(files.keys())

        issues = check_typescript_integrity(files, known_paths, fetch_content=lambda p: None)
        assert issues == []

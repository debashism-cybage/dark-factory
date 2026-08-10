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
    extract_reactive_member_kinds,
    is_app_zoneless,
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
        routes_content = (
            "import { authGuard } from './guards/auth.guard';\nexport const routes = [];"
        )
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


class TestExtractReactiveMemberKinds:
    def test_signal_via_asreadonly(self):
        content = """
        export class AuthService {
            private loading = signal(false);
            readonly isLoading = this.loading.asReadonly();
        }
        """
        kinds = extract_reactive_member_kinds(content, "AuthService")
        assert kinds.get("isLoading") == "signal"

    def test_signal_via_type_annotation(self):
        content = """
        export class AuthService {
            readonly isLoading: Signal<boolean> = computed(() => this.loading());
        }
        """
        kinds = extract_reactive_member_kinds(content, "AuthService")
        assert kinds.get("isLoading") == "signal"

    def test_observable_via_type_annotation(self):
        content = """
        export class AuthService {
            readonly loading$: Observable<boolean> = this.loadingSubject.asObservable();
        }
        """
        kinds = extract_reactive_member_kinds(content, "AuthService")
        assert kinds.get("loading$") == "observable"

    def test_observable_via_subject_init(self):
        content = """
        export class AuthService {
            private loadingSubject = new BehaviorSubject<boolean>(false);
        }
        """
        kinds = extract_reactive_member_kinds(content, "AuthService")
        assert kinds.get("loadingSubject") == "observable"

    def test_ambiguous_property_omitted(self):
        content = """
        export class AuthService {
            readonly maxRetries = 3;
        }
        """
        kinds = extract_reactive_member_kinds(content, "AuthService")
        assert "maxRetries" not in kinds


class TestSignalObservableMisuseRealWorldBug:
    """
    Reproduces the exact production failure:
    TS2339: Property 'pipe' does not exist on type 'Signal<boolean>'.
        authService.isLoading.pipe(...)
    where isLoading is declared via `.asReadonly()` (a Signal), not an
    Observable.
    """

    def test_pipe_on_signal_is_flagged(self):
        guard_content = """
        import { AuthService } from '../services/auth.service';
        export const authGuard: CanActivateFn = () => {
            const authService = inject(AuthService);
            return authService.isLoading.pipe(
                map((loading) => !loading)
            );
        };
        """
        files = {"src/app/guards/auth.guard.ts": guard_content}
        known_paths = {"src/app/guards/auth.guard.ts", "src/app/services/auth.service.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/services/auth.service.ts":
                return """
                export class AuthService {
                    private loading = signal(false);
                    readonly isLoading = this.loading.asReadonly();
                }
                """
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)

        assert len(issues) == 1
        assert "pipe" in issues[0]["issue"]
        assert "Signal" in issues[0]["issue"]
        assert "isLoading()" in issues[0]["fix"] or "toObservable" in issues[0]["fix"]

    def test_subscribe_on_signal_is_flagged(self):
        content = """
        import { AuthService } from './services/auth.service';
        export class Foo {
            constructor(private authService: AuthService) {
                this.authService.isLoading.subscribe((v) => console.log(v));
            }
        }
        """
        files = {"src/app/foo.ts": content}
        known_paths = {"src/app/foo.ts", "src/app/services/auth.service.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/services/auth.service.ts":
                return "export class AuthService {\n readonly isLoading = signal(false);\n}"
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert len(issues) == 1
        assert "subscribe" in issues[0]["issue"]

    def test_set_on_observable_is_flagged(self):
        content = """
        import { AuthService } from './services/auth.service';
        export class Foo {
            constructor(private authService: AuthService) {
                this.authService.loading$.set(true);
            }
        }
        """
        files = {"src/app/foo.ts": content}
        known_paths = {"src/app/foo.ts", "src/app/services/auth.service.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/services/auth.service.ts":
                return "export class AuthService {\n readonly loading$: Observable<boolean> = of(false);\n}"
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert len(issues) == 1
        assert "set" in issues[0]["issue"]

    def test_correct_signal_usage_not_flagged(self):
        # Calling the signal directly (isLoading()) is correct and must not
        # be flagged.
        content = """
        import { AuthService } from '../services/auth.service';
        export const authGuard: CanActivateFn = () => {
            const authService = inject(AuthService);
            return !authService.isLoading();
        };
        """
        files = {"src/app/guards/auth.guard.ts": content}
        known_paths = {"src/app/guards/auth.guard.ts", "src/app/services/auth.service.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/services/auth.service.ts":
                return "export class AuthService {\n readonly isLoading = signal(false).asReadonly();\n}"
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert issues == []

    def test_correct_observable_usage_not_flagged(self):
        content = """
        import { AuthService } from '../services/auth.service';
        export const authGuard: CanActivateFn = () => {
            const authService = inject(AuthService);
            return authService.loading$.pipe(map((v) => !v));
        };
        """
        files = {"src/app/guards/auth.guard.ts": content}
        known_paths = {"src/app/guards/auth.guard.ts", "src/app/services/auth.service.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/services/auth.service.ts":
                return "export class AuthService {\n readonly loading$: Observable<boolean> = of(false);\n}"
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert issues == []

    def test_ambiguous_member_not_flagged(self):
        # A plain number/string property must never trigger a
        # signal/observable mismatch, even if some method is called on it
        # that happens to share a name with a Signal/Observable method.
        content = """
        import { ConfigService } from './services/config.service';
        export class Foo {
            constructor(private configService: ConfigService) {
                this.configService.retryPolicy.set(3);
            }
        }
        """
        files = {"src/app/foo.ts": content}
        known_paths = {"src/app/foo.ts", "src/app/services/config.service.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/services/config.service.ts":
                return "export class ConfigService {\n readonly retryPolicy = new Map<string, number>();\n}"
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert issues == []


class TestIsAppZoneless:
    def test_true_when_no_bootstrap_files_reference_zone(self):
        files = {
            "src/app/app.config.ts": (
                "export const appConfig = { providers: [provideRouter(routes)] };"
            )
        }
        assert is_app_zoneless(files) is True

    def test_false_when_zone_js_import_present(self):
        files = {"src/main.ts": "import 'zone.js';\nbootstrapApplication(App);"}
        assert is_app_zoneless(files) is False

    def test_false_when_provideZoneChangeDetection_present(self):
        files = {
            "src/app/app.config.ts": (
                "providers: [provideZoneChangeDetection({ eventCoalescing: true })]"
            )
        }
        assert is_app_zoneless(files) is False

    def test_false_when_no_bootstrap_files_available(self):
        # Conservative default: don't guess zoneless without evidence.
        assert is_app_zoneless({}) is False


class TestZonelessUnsafeMutationRealWorldBug:
    """
    Reproduces the exact production failure from SCRUM-11: ProductsComponent
    mutated plain fields (loading/products/error) inside an HTTP
    .subscribe() callback. The API call succeeded and data arrived, but
    since this app is zoneless, the loading spinner (*ngIf="loading")
    never disappeared because Angular was never told to re-render.
    """

    PRODUCTS_COMPONENT = """
    import { Component, OnInit } from '@angular/core';
    import { HttpClient } from '@angular/common/http';

    @Component({
      selector: 'app-products',
      template: `<div *ngIf="loading">Loading...</div>`
    })
    export class ProductsComponent implements OnInit {
      products: any[] = [];
      loading: boolean = false;
      error: string | null = null;

      constructor(private http: HttpClient) {}

      ngOnInit(): void {
        this.fetchProducts();
      }

      fetchProducts(): void {
        this.loading = true;
        this.http.get('/api/products').subscribe({
          next: (response: any) => {
            this.products = response.products;
            this.loading = false;
          },
          error: () => {
            this.error = 'Failed to load';
            this.loading = false;
          }
        });
      }
    }
    """

    APP_CONFIG_ZONELESS = (
        "export const appConfig = { providers: [provideRouter(routes)] };"
    )
    MAIN_TS_ZONELESS = "bootstrapApplication(App, appConfig).catch(console.error);"

    def test_flags_plain_field_mutation_in_subscribe_when_zoneless(self):
        files = {"src/app/products/products.ts": self.PRODUCTS_COMPONENT}
        known_paths = {
            "src/app/products/products.ts",
            "src/app/app.config.ts",
            "src/main.ts",
        }

        def fetch(path: str) -> str | None:
            if path == "src/app/app.config.ts":
                return self.APP_CONFIG_ZONELESS
            if path == "src/main.ts":
                return self.MAIN_TS_ZONELESS
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)

        flagged_fields = {i["issue"].split("'")[1] for i in issues}
        assert "loading" in flagged_fields
        assert "products" in flagged_fields
        assert "error" in flagged_fields

    def test_not_flagged_when_app_has_zone_js(self):
        files = {"src/app/products/products.ts": self.PRODUCTS_COMPONENT}
        known_paths = {
            "src/app/products/products.ts",
            "src/app/app.config.ts",
            "src/main.ts",
        }

        def fetch(path: str) -> str | None:
            if path == "src/app/app.config.ts":
                return self.APP_CONFIG_ZONELESS
            if path == "src/main.ts":
                return "import 'zone.js';\n" + self.MAIN_TS_ZONELESS
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert issues == []

    def test_not_flagged_when_no_bootstrap_files_found(self):
        # No app.config.ts/main.ts in known_paths -> can't confirm zoneless
        # -> must not flag (avoid false positives from incomplete context).
        files = {"src/app/products/products.ts": self.PRODUCTS_COMPONENT}
        known_paths = {"src/app/products/products.ts"}

        issues = check_typescript_integrity(files, known_paths, fetch_content=lambda p: None)
        assert issues == []

    def test_signal_based_component_not_flagged(self):
        # The FIXED version: using signal()/.set() instead of plain fields.
        content = """
        import { Component, OnInit, signal } from '@angular/core';
        import { HttpClient } from '@angular/common/http';

        @Component({ selector: 'app-products', template: `` })
        export class ProductsComponent implements OnInit {
          products = signal<any[]>([]);
          loading = signal(false);

          constructor(private http: HttpClient) {}

          ngOnInit(): void {
            this.fetchProducts();
          }

          fetchProducts(): void {
            this.loading.set(true);
            this.http.get('/api/products').subscribe({
              next: (response: any) => {
                this.products.set(response.products);
                this.loading.set(false);
              }
            });
          }
        }
        """
        files = {"src/app/products/products.ts": content}
        known_paths = {
            "src/app/products/products.ts",
            "src/app/app.config.ts",
            "src/main.ts",
        }

        def fetch(path: str) -> str | None:
            if path == "src/app/app.config.ts":
                return self.APP_CONFIG_ZONELESS
            if path == "src/main.ts":
                return self.MAIN_TS_ZONELESS
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert issues == []

    def test_mutation_outside_callback_not_flagged(self):
        # Direct field assignment outside any subscribe/then is a
        # synchronous mutation within the same change-detection cycle that
        # triggered it (e.g. a click handler) -- always safe, zoneless or
        # not. Only async-callback mutations are the actual bug.
        content = """
        import { Component } from '@angular/core';

        @Component({ selector: 'app-foo', template: `` })
        export class FooComponent {
          count: number = 0;

          increment(): void {
            this.count = this.count + 1;
          }
        }
        """
        files = {"src/app/foo.ts": content}
        known_paths = {"src/app/foo.ts", "src/app/app.config.ts", "src/main.ts"}

        def fetch(path: str) -> str | None:
            if path == "src/app/app.config.ts":
                return self.APP_CONFIG_ZONELESS
            if path == "src/main.ts":
                return self.MAIN_TS_ZONELESS
            return None

        issues = check_typescript_integrity(files, known_paths, fetch_content=fetch)
        assert issues == []

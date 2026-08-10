"""
Deterministic (non-LLM) static checks for TypeScript/Angular code.

Why this exists:
The Development Agent's previous "build validation" step asked an LLM to
*read* generated code and judge whether it would compile. LLMs are unreliable
at this — they share the same blind spots as the LLM that wrote the code in
the first place. In practice this missed exactly the errors a real compiler
catches instantly:
    TS2307 Cannot find module '...'
    TS2339 Property 'X' does not exist on type '...'
    TS2551 Property 'X' does not exist on type '...'. Did you mean 'Y'?

This module implements a lightweight, regex-based cross-reference checker
that is grounded in ACTUAL file content pulled from the repository, not
probabilistic text review:
    - Does every relative import path resolve to a real file?
    - Does every named import / dynamic-import member access match a real
      export in the target file?
    - Does every property access on an Angular-injected service match a
      real member of that service's class?
    - Does code call RxJS-only methods (.pipe/.subscribe/etc.) on a member
      that is actually an Angular Signal, or Signal-only methods
      (.set/.update/.asReadonly) on a member that is actually an Observable?
      (e.g. `authService.isLoading.pipe(...)` when `isLoading` is a
      `Signal<boolean>`, not an `Observable<boolean>` — this exact mistake
      has shipped before and is NOT caught by member-existence checks alone,
      since `pipe` genuinely isn't a member of the service class at all.)
    - In a zoneless Angular app (no zone.js / no provideZoneChangeDetection
      in the app's bootstrap config), does a component mutate its own plain
      (non-Signal) class fields inside an RxJS `.subscribe()` callback or a
      Promise `.then()` callback? Without zone.js patching async APIs,
      Angular has no way to know the view needs re-rendering after such a
      mutation — the data/state updates correctly in memory, but the
      template never re-evaluates, so e.g. a loading spinner bound to a
      plain `loading` field stays visible forever even after `loading` is
      set to `false`. This exact bug has shipped before (an HTTP call
      completed successfully but the loading indicator never went away).
      This check only applies when the file/repo context confirms the app
      is zoneless; it is a no-op (never flags anything) when zone.js is
      configured, since that pattern is completely safe there.

This is intentionally generic — it runs identically for every ticket, not
just a specific one — and is grounded entirely in repository content, so it
has no ticket-specific logic.

LIMITATIONS (by design — this is a fast heuristic checker, not a real parser):
    - Only relative imports (starting with '.') are checked. Package imports
      (e.g. '@angular/core', 'rxjs') are not resolvable without node_modules
      and are skipped.
    - Class member extraction uses brace-matching + regexes, not a real AST.
      It can miss unusual formatting. To avoid false positives, checks are
      skipped entirely for a class if member extraction finds nothing.
    - Import/export parsing assumes reasonably standard TypeScript syntax
      (the vast majority of real-world Angular code). Re-export chains
      (`export * from './x'`) are not followed.
    - Does not replace a real compiler — it is a first line of defense that
      catches the most common and costly mistakes (wrong path, wrong name)
      before a human ever sees a broken PR.
"""

import difflib
import posixpath
import re
from collections.abc import Callable

# ---------------------------------------------------------------------------
# Identifier / regex building blocks
# ---------------------------------------------------------------------------

# JS/TS identifiers used as property/member names may legitimately end with
# '$' (RxJS convention for Observables, e.g. `loading$`). Standard \w does
# not include '$', so member/property regexes explicitly allow it.
_MEMBER_NAME = r"[A-Za-z_$][\w$]*"

_IMPORT_RE = re.compile(
    r"import\s+(?:type\s+)?(?P<clause>[^;]+?)\s+from\s+['\"](?P<path>[^'\"]+)['\"]"
)

_DYNAMIC_THEN_RE = re.compile(
    r"import\(\s*['\"](?P<path>[^'\"]+)['\"]\s*\)"
    r"\s*\.then\(\s*\(?\s*(?P<binding>\w+)\s*\)?\s*=>\s*\(?\s*"
    r"(?P=binding)\.(?P<member>" + _MEMBER_NAME + r")"
)

_EXPORT_DECL_RE = re.compile(
    r"export\s+(?:default\s+)?(?:abstract\s+)?(?:class|interface|function|const|let|var|enum)\s+(\w+)"
)
_EXPORT_TYPE_RE = re.compile(r"export\s+type\s+(\w+)")
_EXPORT_BRACE_RE = re.compile(r"export\s*\{([^}]*)\}")
_EXPORT_DEFAULT_RE = re.compile(r"export\s+default\b")

_CTOR_RE = re.compile(r"constructor\s*\(([^)]*)\)", re.DOTALL)
_CTOR_PARAM_RE = re.compile(r"(?:private|public|protected|readonly)\s+(\w+)\s*:\s*(\w+)")
_INJECT_ASSIGN_RE = re.compile(
    r"(?:private|public|protected|readonly)?\s*(\w+)\s*(?::\s*\w+\s*)?=\s*inject\(\s*(\w+)\s*\)"
)

_GETTER_RE = re.compile(r"\bget\s+(" + _MEMBER_NAME + r")\s*\(")
_SETTER_RE = re.compile(r"\bset\s+(" + _MEMBER_NAME + r")\s*\(")
_METHOD_RE = re.compile(
    r"(?:^|\n)\s*(?:public|private|protected|static|readonly|async)*\s*("
    + _MEMBER_NAME
    + r")\s*\([^)]*\)\s*(?::\s*[\w<>\[\],.\s|]+)?\s*\{"
)
_PROPERTY_RE = re.compile(
    r"(?:^|\n)\s*(?:public|private|protected|static|readonly)*\s*("
    + _MEMBER_NAME
    + r")\s*[:=]\s*[^(].*?;"
)

# Captures name + optional type annotation + initializer, used to classify a
# property as a Signal or an Observable so reactive-API misuse can be caught
# (see _classify_reactive_kind below).
_PROPERTY_DECL_RE = re.compile(
    r"(?:^|\n)\s*(?:public|private|protected|static|readonly)*\s*("
    + _MEMBER_NAME
    + r")\s*(?::\s*(?P<type>[\w<>\[\],.\s|]+?))?\s*=\s*(?P<init>[^(].*?);"
)

_RESERVED_METHOD_NAMES = {"constructor", "if", "for", "while", "switch", "catch", "else"}

# Heuristics for classifying whether a class member is an Angular Signal or
# an RxJS Observable, based on its type annotation and/or initializer text.
_SIGNAL_TYPE_HINT_RE = re.compile(r"\b(?:Writable)?Signal\s*<")
_SIGNAL_INIT_HINT_RE = re.compile(r"\b(?:signal|computed)\s*\(|\.asReadonly\s*\(\s*\)")
_OBSERVABLE_TYPE_HINT_RE = re.compile(r"\b(?:Observable|Subject|BehaviorSubject|ReplaySubject)\s*<")
_OBSERVABLE_INIT_HINT_RE = re.compile(
    r"\bnew\s+(?:Subject|BehaviorSubject|ReplaySubject)\b"
    r"|\.pipe\s*\(|\.asObservable\s*\(\s*\)"
    r"|\b(?:of|from|timer|interval|merge|combineLatest)\s*\("
)

# Methods that only exist on RxJS Observables, never on Angular Signals.
_OBSERVABLE_ONLY_METHODS = {"pipe", "subscribe", "toPromise", "forEach"}
# Methods that only exist on Angular WritableSignals, never on Observables.
_SIGNAL_ONLY_METHODS = {"set", "update", "asReadonly", "mutate"}


# ---------------------------------------------------------------------------
# Import / export parsing
# ---------------------------------------------------------------------------


def _parse_clause(clause: str) -> dict:
    """Parse the clause of an `import <clause> from '...'` statement."""
    clause = clause.strip()

    ns_match = re.match(r"^\*\s+as\s+(\w+)$", clause)
    if ns_match:
        return {"default": None, "named": [], "namespace": ns_match.group(1)}

    brace_match = re.search(r"\{(.*)\}", clause, re.DOTALL)
    named: list[tuple[str, str]] = []
    default_name: str | None = None

    if brace_match:
        named_part = brace_match.group(1)
        before = clause[: brace_match.start()].strip().rstrip(",").strip()
        if before and re.match(r"^\w+$", before):
            default_name = before
        for item in named_part.split(","):
            item = item.strip()
            if not item:
                continue
            if " as " in item:
                exported, local = item.split(" as", 1)
                named.append((local.strip(), exported.strip()))
            else:
                named.append((item, item))
    elif re.match(r"^\w+$", clause):
        default_name = clause

    return {"default": default_name, "named": named, "namespace": None}


def parse_static_imports(content: str) -> list[dict]:
    """Parse all `import ... from '...'` statements in a file."""
    results: list[dict] = []
    for m in _IMPORT_RE.finditer(content):
        parsed = _parse_clause(m.group("clause"))
        parsed["module"] = m.group("path")
        results.append(parsed)
    return results


def parse_dynamic_then_imports(content: str) -> list[dict]:
    """
    Parse `import('./x').then((m) => m.Member)` patterns — the standard
    Angular lazy-route `loadComponent`/`loadChildren` shape.
    """
    return [
        {"module": m.group("path"), "member": m.group("member")}
        for m in _DYNAMIC_THEN_RE.finditer(content)
    ]


def extract_exports(content: str) -> set[str]:
    """Extract the set of names a file exports (best-effort, regex-based)."""
    names: set[str] = set()

    for m in _EXPORT_DECL_RE.finditer(content):
        names.add(m.group(1))
    for m in _EXPORT_TYPE_RE.finditer(content):
        names.add(m.group(1))
    for m in _EXPORT_BRACE_RE.finditer(content):
        for item in m.group(1).split(","):
            item = item.strip()
            if not item:
                continue
            if " as " in item:
                _, exported = item.split(" as", 1)
                names.add(exported.strip())
            else:
                names.add(item)
    if _EXPORT_DEFAULT_RE.search(content):
        names.add("default")

    return names


# ---------------------------------------------------------------------------
# Module path resolution
# ---------------------------------------------------------------------------


_RESOLVABLE_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")


def resolve_module_path(from_path: str, module_path: str, known_paths: set[str]) -> str | None:
    """
    Resolve a relative import path (e.g. './auth/auth.guard') against the
    repository's known file paths, trying common TS extension/index
    conventions. Returns None if the import isn't relative or can't be
    resolved to a real file.

    NOTE: Angular/TS files conventionally have dots in their base name
    (auth.guard.ts, auth.service.ts, app.routes.ts). An import path like
    './auth/auth.guard' therefore already "looks like" it has an extension
    if you naively use splitext (it would see '.guard'). We must not rely on
    splitext here — instead, only treat the path as already-complete if it
    ends with one of the recognized TS/JS extensions; otherwise always try
    both the bare path and the path with an extension appended.
    """
    if not module_path.startswith("."):
        return None

    base_dir = posixpath.dirname(from_path)
    combined = posixpath.normpath(posixpath.join(base_dir, module_path)).replace("\\", "/")

    if combined.endswith(_RESOLVABLE_EXTENSIONS):
        candidates = [combined]
    else:
        candidates = [
            f"{combined}.ts",
            f"{combined}.tsx",
            f"{combined}.js",
            f"{combined}.jsx",
            combined,  # exact match with no extension (rare, but possible)
            f"{combined}/index.ts",
            f"{combined}/index.tsx",
        ]

    for candidate in candidates:
        if candidate in known_paths:
            return candidate

    return None


# ---------------------------------------------------------------------------
# Injected service / class member analysis
# ---------------------------------------------------------------------------


def extract_injected_services(content: str) -> dict[str, str]:
    """
    Find Angular dependency-injection bindings: constructor params
    (`private authService: AuthService`) and `inject(AuthService)` field
    assignments. Returns {local_variable_name: class_name}.
    """
    services: dict[str, str] = {}

    ctor_match = _CTOR_RE.search(content)
    if ctor_match:
        for m in _CTOR_PARAM_RE.finditer(ctor_match.group(1)):
            services[m.group(1)] = m.group(2)

    for m in _INJECT_ASSIGN_RE.finditer(content):
        services[m.group(1)] = m.group(2)

    return services


def _extract_class_body(content: str, class_name: str) -> str | None:
    """
    Find the body of `class <class_name> { ... }` via brace-matching.
    Shared by every function below that needs to scan a specific class's
    members. Returns None if the class can't be found or its closing brace
    can't be matched — callers should treat that as "skip this class"
    rather than risk false positives from a failed/partial parse.
    """
    class_match = re.search(rf"class\s+{re.escape(class_name)}\b[^{{]*\{{", content)
    if not class_match:
        return None

    start = class_match.end() - 1
    depth = 0
    end: int | None = None
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end is None:
        return None

    return content[start + 1 : end]


def extract_class_members(content: str, class_name: str) -> set[str] | None:
    """
    Extract member names (properties, getters, setters, methods) declared
    directly on a class body via brace-matching + regexes.

    Returns None if the class can't be found or its body can't be matched —
    callers should skip member-existence checks in that case rather than
    risk false positives from a failed/partial parse.
    """
    body = _extract_class_body(content, class_name)
    if body is None:
        return None

    members: set[str] = set()

    for m in _GETTER_RE.finditer(body):
        members.add(m.group(1))
    for m in _SETTER_RE.finditer(body):
        members.add(m.group(1))
    for m in _METHOD_RE.finditer(body):
        name = m.group(1)
        if name not in _RESERVED_METHOD_NAMES:
            members.add(name)
    for m in _PROPERTY_RE.finditer(body):
        members.add(m.group(1))

    return members


def find_member_accesses(content: str, var_names: list[str]) -> list[tuple[str, str, int]]:
    """
    Find `varName.member` accesses for a set of variable names.
    Returns list of (var_name, member_name, line_number).
    """
    if not var_names:
        return []

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(v) for v in var_names) + r")\." + "(" + _MEMBER_NAME + ")"
    )
    results: list[tuple[str, str, int]] = []
    for m in pattern.finditer(content):
        line_no = content.count("\n", 0, m.start()) + 1
        results.append((m.group(1), m.group(2), line_no))
    return results


def extract_reactive_member_kinds(content: str, class_name: str) -> dict[str, str]:
    """
    Classify each property declared on a class as "signal" or "observable"
    based on its type annotation and/or initializer, using heuristics — not
    a real type-checker. This is what lets the checker catch the exact
    mistake that shipped in production: calling `.pipe()`/`.subscribe()` on
    a class member that IS a real member (so member-existence checks pass)
    but is actually a Signal, not an Observable (or vice versa), e.g.
    `authService.isLoading.pipe(...)` when `isLoading` is declared as
    `readonly isLoading = this.loading.asReadonly();` (a Signal<boolean>).

    Returns {member_name: "signal" | "observable"}. Members whose kind can't
    be confidently determined are omitted entirely — no false positives from
    ambiguous declarations.
    """
    body = _extract_class_body(content, class_name)
    if body is None:
        return {}

    kinds: dict[str, str] = {}

    for m in _PROPERTY_DECL_RE.finditer(body):
        name = m.group(1)
        type_hint = m.group("type") or ""
        init = m.group("init") or ""
        combined = f"{type_hint} {init}"

        is_signal = bool(
            _SIGNAL_TYPE_HINT_RE.search(combined) or _SIGNAL_INIT_HINT_RE.search(combined)
        )
        is_observable = bool(
            _OBSERVABLE_TYPE_HINT_RE.search(combined) or _OBSERVABLE_INIT_HINT_RE.search(combined)
        )

        if is_signal and not is_observable:
            kinds[name] = "signal"
        elif is_observable and not is_signal:
            kinds[name] = "observable"
        # Ambiguous or neither -> omit, to avoid false positives.

    return kinds


def find_chained_member_calls(
    content: str, var_names: list[str]
) -> list[tuple[str, str, str, int]]:
    """
    Find `varName.member.methodCall(` patterns — e.g.
    `authService.isLoading.pipe(` — for a set of variable names. This is the
    two-hop access pattern needed to catch calling a reactive-only method
    (.pipe/.subscribe/.set/.update) on a specific member of an injected
    service, as opposed to a direct call on the service itself.

    Returns list of (var_name, member_name, method_name, line_number).
    """
    if not var_names:
        return []

    pattern = re.compile(
        r"\b("
        + "|".join(re.escape(v) for v in var_names)
        + r")\."
        + "("
        + _MEMBER_NAME
        + r")\."
        + "("
        + _MEMBER_NAME
        + r")\s*\("
    )
    results: list[tuple[str, str, str, int]] = []
    for m in pattern.finditer(content):
        line_no = content.count("\n", 0, m.start()) + 1
        results.append((m.group(1), m.group(2), m.group(3), line_no))
    return results


# ---------------------------------------------------------------------------
# Zoneless change-detection safety
# ---------------------------------------------------------------------------

# Files that typically bootstrap the app and would import/configure zone.js
# or provideZoneChangeDetection, used to decide whether an app is zoneless.
_BOOTSTRAP_HINT_PATHS = ("main.ts", "app.config.ts", "app.config.server.ts")

_ZONE_JS_HINT_RE = re.compile(r"['\"]zone\.js['\"]|provideZoneChangeDetection\s*\(")

# A field is declared as a Signal if its initializer/type matches the same
# heuristics used for reactive-kind classification elsewhere in this module.
# Plain fields are anything NOT matching a Signal declaration pattern.
_PLAIN_FIELD_DECL_RE = re.compile(
    r"(?:^|\n)\s*(?:public|private|protected|static|readonly)*\s*("
    + _MEMBER_NAME
    + r")\s*(?::\s*(?P<type>[\w<>\[\],.\s|]+?))?\s*=\s*(?P<init>[^(].*?);"
)

# `this.field = ...` or `this.field.set(...)`/`this.field.update(...)` (the
# latter two are Signal writes, not plain-field mutation, so they must be
# excluded from what counts as an unsafe plain-field assignment).
_THIS_FIELD_ASSIGN_RE = re.compile(r"\bthis\." + "(" + _MEMBER_NAME + r")" + r"\s*=(?!=)")

# Boundaries of an RxJS `.subscribe({...})` or `.subscribe(fn)` call, and a
# Promise `.then(...)` call — the callback bodies where zoneless-unsafe
# mutation typically happens.
_ASYNC_CALLBACK_START_RE = re.compile(r"\.(?:subscribe|then)\s*\(")


def is_app_zoneless(bootstrap_files: dict[str, str]) -> bool:
    """
    Determine whether an Angular app is running zoneless, based on the
    content of its bootstrap files (main.ts, app.config.ts, etc.).

    An app is considered zoneless if none of the provided bootstrap files
    reference 'zone.js' or call provideZoneChangeDetection(...). If no
    bootstrap files are provided/available, this conservatively returns
    False (i.e. assumes zone-full / does not flag anything) rather than
    guessing, to avoid false positives when repo context is incomplete.

    Args:
        bootstrap_files: path -> content, for any of _BOOTSTRAP_HINT_PATHS
            (or any file that looks like an app bootstrap/config file)
            that could be fetched from the repository.
    """
    if not bootstrap_files:
        return False

    return all(not _ZONE_JS_HINT_RE.search(content) for content in bootstrap_files.values())


def _find_async_callback_bodies(content: str) -> list[tuple[int, int]]:
    """
    Find the (start, end) character offsets of the body of every
    `.subscribe(...)` / `.then(...)` call in content, via brace/paren
    matching starting right after the opening `(`.

    Handles both callback styles:
        obs.subscribe({ next: (x) => { ... } })
        obs.subscribe((x) => { ... })
        promise.then((x) => { ... })
    by matching from the opening paren of subscribe/then to its balanced
    closing paren -- the whole argument list, which is a safe superset of
    the individual arrow-function bodies and is sufficient for scanning for
    `this.field = ...` mutations inside it.
    """
    bodies: list[tuple[int, int]] = []
    for m in _ASYNC_CALLBACK_START_RE.finditer(content):
        start = m.end() - 1  # position of the opening '('
        depth = 0
        end: int | None = None
        for i in range(start, len(content)):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is not None:
            bodies.append((start + 1, end))
    return bodies


def extract_plain_field_names(content: str, class_name: str) -> set[str]:
    """
    Extract the names of fields on a class that are PLAIN (not Signals) —
    i.e. fields that would need zone.js to trigger a re-render when mutated
    after component construction. Fields declared via `signal(...)`,
    `computed(...)`, or typed `Signal<T>`/`WritableSignal<T>` are excluded,
    since mutating those is always zoneless-safe (`.set()`/`.update()`
    notify Angular directly regardless of zone.js).

    Returns an empty set if the class can't be found/parsed — callers
    should treat that as "nothing to check" rather than guessing.
    """
    body = _extract_class_body(content, class_name)
    if body is None:
        return set()

    plain_fields: set[str] = set()
    for m in _PLAIN_FIELD_DECL_RE.finditer(body):
        name = m.group(1)
        type_hint = m.group("type") or ""
        init = m.group("init") or ""
        combined = f"{type_hint} {init}"
        is_signal = bool(
            _SIGNAL_TYPE_HINT_RE.search(combined) or _SIGNAL_INIT_HINT_RE.search(combined)
        )
        if not is_signal:
            plain_fields.add(name)

    return plain_fields


def find_unsafe_zoneless_mutations(
    content: str,
    class_name: str,
    plain_fields: set[str],
) -> list[tuple[str, int]]:
    """
    Find `this.<plainField> = ...` assignments that occur inside an RxJS
    `.subscribe(...)` or Promise `.then(...)` callback body, for a class's
    own plain (non-Signal) fields. In a zoneless app, these mutations never
    trigger a view re-render -- this is exactly the bug pattern that shipped
    in production (loading spinner bound to a plain `loading` field never
    disappearing after an HTTP call completed).

    Returns list of (field_name, line_number).
    """
    if not plain_fields:
        return []

    callback_ranges = _find_async_callback_bodies(content)
    if not callback_ranges:
        return []

    results: list[tuple[str, int]] = []
    for m in _THIS_FIELD_ASSIGN_RE.finditer(content):
        field = m.group(1)
        if field not in plain_fields:
            continue
        pos = m.start()
        if any(start <= pos < end for start, end in callback_ranges):
            line_no = content.count("\n", 0, pos) + 1
            results.append((field, line_no))

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# Matches a self-declared class's export statement, used to find "which
# class in this file am I checking for zoneless-unsafe self-mutation" —
# distinct from _extract_class_body's by-name lookup, since here we don't
# know the class name in advance.
_SELF_CLASS_DECL_RE = re.compile(r"export\s+(?:default\s+)?(?:abstract\s+)?class\s+(\w+)")


def check_typescript_integrity(
    files: dict[str, str],
    known_paths: set[str],
    fetch_content: Callable[[str], str | None],
) -> list[dict[str, str]]:
    """
    Cross-reference every relative import, dynamic-import member access, and
    injected-service property access in `files` against real repository
    content. Purely deterministic — no LLM calls.

    Args:
        files: path -> content for the files to check (the changeset).
        known_paths: set of all known file paths in the repository,
            INCLUDING the paths already present in `files` (so newly
            created files count as resolvable targets for other files in
            the same changeset).
        fetch_content: callable(path) -> content or None, used to lazily
            fetch content of referenced files that aren't part of the
            changeset itself (e.g. an existing service/component file).

    Returns:
        List of issue dicts: {"file": ..., "issue": ..., "fix": ...}.
    """
    issues: list[dict[str, str]] = []
    content_cache: dict[str, str | None] = dict(files)
    zoneless_result: dict[str, bool] = {}

    def get_content(path: str) -> str | None:
        if path not in content_cache:
            content_cache[path] = fetch_content(path)
        return content_cache[path]

    def is_zoneless_app() -> bool:
        # Computed lazily and cached: only fetched if a file in the
        # changeset actually needs the answer (avoids unnecessary fetches
        # for tickets that don't touch any async subscribe/then code).
        if "value" not in zoneless_result:
            bootstrap_contents: dict[str, str] = {}
            for candidate in known_paths:
                base = candidate.rsplit("/", 1)[-1]
                if base in _BOOTSTRAP_HINT_PATHS:
                    content = get_content(candidate)
                    if content:
                        bootstrap_contents[candidate] = content
            zoneless_result["value"] = is_app_zoneless(bootstrap_contents)
        return zoneless_result["value"]

    for path, content in files.items():
        # -----------------------------------------------------------------
        # Zoneless-unsafe plain-field mutation inside .subscribe()/.then()
        # -----------------------------------------------------------------
        self_class_match = _SELF_CLASS_DECL_RE.search(content)
        if self_class_match and is_zoneless_app():
            self_class_name = self_class_match.group(1)
            plain_fields = extract_plain_field_names(content, self_class_name)
            for field, line_no in find_unsafe_zoneless_mutations(
                content, self_class_name, plain_fields
            ):
                issues.append(
                    {
                        "file": path,
                        "issue": (
                            f"'{field}' is a plain field mutated inside a .subscribe()/.then() "
                            f"callback (line {line_no}), but this app is zoneless (no zone.js / "
                            f"provideZoneChangeDetection configured) — Angular will never re-render "
                            f"the view after this assignment, so any template binding to '{field}' "
                            f"(e.g. a loading spinner) will appear stuck even though the underlying "
                            f"value did change."
                        ),
                        "fix": (
                            f"In {path}, convert '{field}' to a Signal (e.g. "
                            f"`{field} = signal(...)`) and write it with `this.{field}.set(...)` "
                            f"inside the callback, then read it as `{field}()` in the template — "
                            f"the same zoneless-safe pattern already used elsewhere in this app."
                        ),
                    }
                )

        # -----------------------------------------------------------------
        # Static imports: does the path resolve? Do named imports exist?
        # -----------------------------------------------------------------
        for imp in parse_static_imports(content):
            module = imp["module"]
            if not module.startswith("."):
                continue

            resolved = resolve_module_path(path, module, known_paths)
            if resolved is None:
                issues.append(
                    {
                        "file": path,
                        "issue": f"Cannot find module '{module}' or its corresponding type declarations",
                        "fix": (
                            f"Update the import path in {path} to point to the file that actually "
                            f"exists in the repository (the current path '{module}' does not resolve)."
                        ),
                    }
                )
                continue

            target_content = get_content(resolved)
            if not target_content:
                continue

            exports = extract_exports(target_content)
            if not exports:
                continue

            for _local_name, exported_name in imp["named"]:
                if exported_name == "default" or exported_name in exports:
                    continue
                suggestion = difflib.get_close_matches(exported_name, list(exports), n=1)
                hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ""
                issues.append(
                    {
                        "file": path,
                        "issue": f"'{resolved}' has no exported member '{exported_name}'.{hint}",
                        "fix": (
                            f"In {path}, import the name that actually exists in {resolved} "
                            f"(available exports: {', '.join(sorted(exports))})."
                        ),
                    }
                )

            if imp["default"] and "default" not in exports:
                issues.append(
                    {
                        "file": path,
                        "issue": f"'{resolved}' has no default export but is imported as a default import",
                        "fix": (
                            f"In {path}, use a named import matching one of {resolved}'s actual exports "
                            f"({', '.join(sorted(exports))}) instead of a default import."
                        ),
                    }
                )

        # -----------------------------------------------------------------
        # Dynamic imports: import('./x').then((m) => m.Member)
        # -----------------------------------------------------------------
        for dyn in parse_dynamic_then_imports(content):
            module = dyn["module"]
            if not module.startswith("."):
                continue

            resolved = resolve_module_path(path, module, known_paths)
            if resolved is None:
                issues.append(
                    {
                        "file": path,
                        "issue": f"Cannot find module '{module}' for dynamic import",
                        "fix": f"Update the dynamic import path in {path} to point to a file that actually exists.",
                    }
                )
                continue

            target_content = get_content(resolved)
            if not target_content:
                continue

            exports = extract_exports(target_content)
            member = dyn["member"]
            if exports and member not in exports:
                suggestion = difflib.get_close_matches(member, list(exports), n=1)
                hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ""
                issues.append(
                    {
                        "file": path,
                        "issue": f"Property '{member}' does not exist on type of module '{resolved}'.{hint}",
                        "fix": (
                            f"In {path}, use the actual exported name from {resolved} "
                            f"(available exports: {', '.join(sorted(exports))})."
                        ),
                    }
                )

        # -----------------------------------------------------------------
        # Injected Angular service property/method access
        # -----------------------------------------------------------------
        services = extract_injected_services(content)
        if not services:
            continue

        local_class_to_module: dict[str, str] = {}
        for imp in parse_static_imports(content):
            for _local_name, exported_name in imp["named"]:
                local_class_to_module[exported_name] = imp["module"]

        for var_name, class_name in services.items():
            module = local_class_to_module.get(class_name)
            if not module or not module.startswith("."):
                continue

            resolved = resolve_module_path(path, module, known_paths)
            if not resolved:
                continue

            target_content = get_content(resolved)
            if not target_content:
                continue

            members = extract_class_members(target_content, class_name)
            if not members:
                # Extraction failed or found nothing — skip to avoid false positives.
                continue

            for _accessed_var, member, line_no in find_member_accesses(content, [var_name]):
                if member in members:
                    continue
                suggestion = difflib.get_close_matches(member, list(members), n=1)
                hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ""
                issues.append(
                    {
                        "file": path,
                        "issue": (
                            f"Property '{member}' does not exist on type '{class_name}'.{hint} (line {line_no})"
                        ),
                        "fix": (
                            f"In {path}, use an existing member of {class_name} "
                            f"(available: {', '.join(sorted(members))}) instead of '{member}'."
                        ),
                    }
                )

            # ---------------------------------------------------------------
            # Signal vs Observable API misuse: authService.isLoading.pipe(...)
            # where isLoading is a member that EXISTS (so the check above
            # passes) but is a Signal, not an Observable — or vice versa.
            # ---------------------------------------------------------------
            reactive_kinds = extract_reactive_member_kinds(target_content, class_name)
            if not reactive_kinds:
                continue

            for _accessed_var, member, method, line_no in find_chained_member_calls(
                content, [var_name]
            ):
                kind = reactive_kinds.get(member)
                if kind is None:
                    continue

                if kind == "signal" and method in _OBSERVABLE_ONLY_METHODS:
                    issues.append(
                        {
                            "file": path,
                            "issue": (
                                f"Property '{method}' does not exist on type 'Signal' "
                                f"(line {line_no}): '{member}' on {class_name} is declared as an "
                                f"Angular Signal, not an RxJS Observable, so '.{method}()' is not "
                                f"a valid call."
                            ),
                            "fix": (
                                f"In {path}, read the Signal by calling it directly "
                                f"(e.g. `{var_name}.{member}()`) instead of `.{method}(...)`. "
                                f"If reactive-stream behavior (e.g. `.pipe()`) is actually needed, "
                                f"use `toObservable({var_name}.{member})` from "
                                f"'@angular/core/rxjs-interop' instead of calling '.{method}' "
                                f"directly on the Signal."
                            ),
                        }
                    )
                elif kind == "observable" and method in _SIGNAL_ONLY_METHODS:
                    issues.append(
                        {
                            "file": path,
                            "issue": (
                                f"Property '{method}' does not exist on type 'Observable' "
                                f"(line {line_no}): '{member}' on {class_name} is declared as an "
                                f"RxJS Observable, not an Angular Signal, so '.{method}(...)' is "
                                f"not a valid call."
                            ),
                            "fix": (
                                f"In {path}, use the Observable's actual API (e.g. `.subscribe(...)` "
                                f"or `.pipe(...)`) instead of `.{method}(...)`, which is a Signal-only "
                                f"method."
                            ),
                        }
                    )

    return issues

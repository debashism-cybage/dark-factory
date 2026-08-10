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
from typing import Any

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


def expected_missing_path(from_path: str, module_path: str) -> str:
    """
    Best-effort guess at the file path an unresolved relative import SHOULD
    have pointed to, so a missing dependency can be created at a sane
    location instead of only ever patching the file that imports it.

    Mirrors resolve_module_path's own path-joining logic, but since nothing
    matched in known_paths we have no real file to return — we pick the most
    likely intended path (the module path + '.ts', since that is the
    overwhelming convention for Angular/TS source) so a CREATE can target it.
    """
    base_dir = posixpath.dirname(from_path)
    combined = posixpath.normpath(posixpath.join(base_dir, module_path)).replace("\\", "/")
    if combined.endswith(_RESOLVABLE_EXTENSIONS):
        return combined
    return f"{combined}.ts"


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
# @Input() property vs interface/model field mismatch
# ---------------------------------------------------------------------------

# `@Input() exercise!: Exercise;` / `@Input() exercise: Exercise;` /
# `@Input() exercise?: Exercise;` — captures the bound property name and its
# declared type name so template/class accesses on that property can be
# cross-checked against the type's real fields.
_INPUT_DECL_RE = re.compile(
    r"@Input\(\)\s*(?:public\s+|private\s+|protected\s+|readonly\s+)*("
    + _MEMBER_NAME
    + r")\s*[!?]?\s*:\s*("
    + _MEMBER_NAME
    + r")"
)

_INTERFACE_DECL_RE = re.compile(r"(?:export\s+)?interface\s+(\w+)\b[^{]*\{")

# A single flat interface member: `name: Type;` or `name?: Type;`. The type
# portion excludes braces so this only matches flat (non-nested-object)
# fields — see extract_interface_members's docstring for why that's a
# deliberate safety choice, not an oversight.
_INTERFACE_MEMBER_RE = re.compile(
    r"(?:^|\n)\s*(" + _MEMBER_NAME + r")\s*\??\s*:\s*[^;{}]+;"
)

# Matches a full `import ... from '...'` statement, used to mask out import
# paths before searching for member accesses. This exists because a common
# and entirely valid naming convention — `@Input() exercise: Exercise` bound
# to a model imported `from '../exercise.model'` — causes the raw text
# "exercise.model" inside the import path string to look exactly like a
# genuine `exercise.model` member access to a naive regex. Real Angular
# code hits this collision routinely (the property name is usually the
# lowercased type name, and the model file is usually named after it too),
# so this isn't a contrived edge case.
_IMPORT_STATEMENT_RE = re.compile(
    r"import\s+(?:type\s+)?[^;]+?from\s+['\"][^'\"]+['\"]\s*;?"
)


def _mask_import_statements(content: str) -> str:
    """
    Replace the text of every `import ... from '...'` statement with spaces
    of the same length (preserving newlines), so member-access regexes
    can't accidentally match text that only appears inside an import path
    string. Preserves overall content length/line numbers so any line
    numbers computed against the masked content still match the original.
    """

    def _blank(m: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return _IMPORT_STATEMENT_RE.sub(_blank, content)


def _extract_interface_body(content: str, interface_name: str) -> str | None:
    """
    Find the body of `interface <interface_name> { ... }` via brace-matching.
    Returns None if the interface can't be found or its closing brace can't
    be matched.
    """
    match = re.search(rf"interface\s+{re.escape(interface_name)}\b[^{{]*\{{", content)
    if not match:
        return None

    start = match.end() - 1
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


def extract_interface_members(content: str, interface_name: str) -> set[str] | None:
    """
    Extract the field names declared directly on a TypeScript `interface`
    (e.g. `interface Exercise { name: string; gifUrl: string; }`).

    This is deliberately conservative: if the interface body contains a
    brace beyond its own opening one (i.e. a field has a nested object type
    like `meta: { total: number };`), this returns None rather than a
    partial/wrong member set — `_INTERFACE_MEMBER_RE` cannot safely parse
    nested object types line-by-line, and guessing wrong here would cause
    false positives (flagging a real field as nonexistent). Real-world
    Angular API-response models are overwhelmingly flat, so this covers the
    common case without risking incorrect flags on the uncommon one.

    Returns None if the interface can't be found, can't be parsed, or
    extends another interface (whose fields we can't see here) — callers
    should skip the check entirely in that case, not assume an empty set.
    """
    body = _extract_interface_body(content, interface_name)
    if body is None:
        return None

    if "extends" in content[: content.find(body)].rsplit("interface", 1)[-1]:
        # `interface X extends Y { ... }` — Y's fields aren't visible here;
        # skip rather than risk flagging an inherited field as missing.
        return None

    if "{" in body:
        # Nested object type field(s) — see docstring above.
        return None

    members: set[str] = set()
    for m in _INTERFACE_MEMBER_RE.finditer(body):
        members.add(m.group(1))

    return members if members else None


def extract_input_bindings(content: str, class_name: str) -> dict[str, str]:
    """
    Find `@Input()` property declarations within a specific class body and
    their declared type names. Returns {property_name: type_name}.

    E.g. for `@Input() exercise!: Exercise;` inside `class ExerciseCardComponent`,
    returns {"exercise": "Exercise"}.
    """
    body = _extract_class_body(content, class_name)
    if body is None:
        return {}

    return {m.group(1): m.group(2) for m in _INPUT_DECL_RE.finditer(body)}


def resolve_named_import_module(content: str, exported_name: str) -> str | None:
    """
    Find the relative module path a given name is imported from, e.g. for
    `import { Exercise, ExercisesResponse } from '../models/exercise.model';`
    calling this with exported_name="ExercisesResponse" returns
    '../models/exercise.model'. Returns None if the name isn't imported via
    a relative (local) import in this file.
    """
    for imp in parse_static_imports(content):
        for _local, name in imp["named"]:
            if name == exported_name:
                return imp["module"]
    return None


# ---------------------------------------------------------------------------
# Typed callback-parameter member access (RxJS .subscribe/.then callbacks)
# ---------------------------------------------------------------------------

# `(response: ExercisesResponse) => ...` — a single explicitly-typed arrow
# function parameter, the standard shape of an RxJS `.subscribe(...)` /
# Promise `.then(...)` success callback.
_ARROW_TYPED_PARAM_RE = re.compile(
    r"\(\s*(" + _MEMBER_NAME + r")\s*:\s*(" + _MEMBER_NAME + r")\s*\)\s*=>"
)


def find_member_accesses_with_offsets(
    content: str, var_names: list[str]
) -> list[tuple[str, str, int, int]]:
    """
    Like find_member_accesses, but also returns each match's character
    offset (not just its line number), so callers can restrict results to
    a specific region of the file (e.g. one particular callback's body)
    without needing to re-slice content and recompute line numbers against
    a substring.

    Returns list of (var_name, member_name, char_offset, line_number).
    """
    if not var_names:
        return []

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(v) for v in var_names) + r")\." + "(" + _MEMBER_NAME + ")"
    )
    results: list[tuple[str, str, int, int]] = []
    for m in pattern.finditer(content):
        line_no = content.count("\n", 0, m.start()) + 1
        results.append((m.group(1), m.group(2), m.start(), line_no))
    return results


def extract_callback_typed_params(content: str) -> list[tuple[int, int, str, str]]:
    """
    For every RxJS `.subscribe(...)` / Promise `.then(...)` call, find an
    explicitly-typed arrow-function parameter within its argument list
    (e.g. `.subscribe({ next: (response: ExercisesResponse) => {...} })`)
    and return the callback's argument-list character range along with the
    parameter's name and declared type.

    The range is returned (not just the name/type) so member accesses on
    that parameter can be checked ONLY within this specific callback's
    scope, not the whole file — a name like `response` or `err` is commonly
    reused across multiple, unrelated `.subscribe()` calls in the same
    component (e.g. `loadExercises()` and `loadMore()` both declare their
    own `response: ExercisesResponse`), so scoping strictly to the owning
    callback avoids attributing a member access to the wrong declaration.

    Returns: list of (start, end, param_name, type_name) using the same
    [start, end) character-offset convention as _find_async_callback_bodies.
    """
    results: list[tuple[int, int, str, str]] = []
    for start, end in _find_async_callback_bodies(content):
        region = content[start:end]
        m = _ARROW_TYPED_PARAM_RE.search(region)
        if m:
            results.append((start, end, m.group(1), m.group(2)))
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


def find_duplicate_type_definitions(files: dict[str, str]) -> list[dict[str, Any]]:
    """
    Detect the same interface/type name declared in MORE THAN ONE file
    within the same changeset. TypeScript treats each declaration as a
    structurally distinct type even if the names match — if one file
    imports the version from path A and another imports the version from
    path B, passing a value typed by one into something typed by the other
    fails to compile (TS2741/TS2322) even though both are named identically
    and a human skimming the diff would assume they're "the same type".

    This is exactly what happened in PR #35: `src/app/exercises/exercise.model.ts`
    and `src/app/models/exercise.model.ts` were BOTH newly created in the
    same PR, both declaring `export interface Exercise { ... }`, but with
    different fields (`id` vs `exerciseId`). `exercise-card.ts` imported one,
    `exercises.ts` imported the other, and passing an `Exercise` instance
    from one to a component expecting the other failed to compile.

    Grounded entirely in the changeset's own content — no LLM guessing, no
    ticket-specific logic. Runs for every future ticket that creates more
    than one new type/interface file.

    Returns:
        List of issue dicts, one per duplicate name found (paired across
        all files that declare it), in the same {"file", "issue", "fix"}
        shape as the rest of this module's checks.
    """
    declared_in: dict[str, list[str]] = {}
    for path, content in files.items():
        for m in _INTERFACE_DECL_RE.finditer(content):
            declared_in.setdefault(m.group(1), []).append(path)
        for m in _EXPORT_TYPE_RE.finditer(content):
            declared_in.setdefault(m.group(1), []).append(path)

    issues: list[dict[str, Any]] = []
    for type_name, paths in declared_in.items():
        unique_paths = sorted(set(paths))
        if len(unique_paths) < 2:
            continue
        issues.append(
            {
                "file": unique_paths[1],
                "issue": (
                    f"Type/interface '{type_name}' is declared in multiple files in this "
                    f"changeset: {', '.join(unique_paths)}. Even if their fields are "
                    f"identical today, TypeScript treats these as separate types, and any "
                    f"code that imports one and passes a value to something expecting the "
                    f"other will fail to compile (e.g. 'Property X is missing in type "
                    f"...A.{type_name} but required in type ...B.{type_name}')."
                ),
                "fix": (
                    f"Delete the duplicate '{type_name}' declaration and make every file "
                    f"that needs it import from a single shared location "
                    f"(e.g. keep only {unique_paths[0]} and update all other files to "
                    f"import '{type_name}' from there instead of redeclaring it)."
                ),
            }
        )

    return issues


def check_typescript_integrity(
    files: dict[str, str],
    known_paths: set[str],
    fetch_content: Callable[[str], str | None],
) -> list[dict[str, Any]]:
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
        List of issue dicts: {"file": ..., "issue": ..., "fix": ...}. Unresolved
        relative imports (the class of bug that patch-in-place fixes can never
        actually resolve, since the target file doesn't exist) additionally
        carry {"kind": "MISSING_MODULE", "expectedPath": ..., "requiredExports":
        [...], "importingModule": ...} so callers can create the missing file
        instead of only rewriting the importer.
    """
    issues: list[dict[str, Any]] = find_duplicate_type_definitions(files)
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
        # @Input() property member access vs its declared interface/model
        # -----------------------------------------------------------------
        # This catches the exact SCRUM-14 bug: a component declares
        # `@Input() exercise!: Exercise;` and its template accesses
        # `exercise.description`, but `Exercise` never declares a
        # `description` field. Member-existence checks elsewhere in this
        # module only cover injected SERVICES (constructor params /
        # inject()); this covers @Input()-bound view-model objects, which
        # is a distinct and equally common source of TS2339 in Angular
        # component templates (inline templates are just template literals
        # in the .ts file, so find_member_accesses already sees them).
        if self_class_match:
            input_bindings = extract_input_bindings(content, self_class_match.group(1))
            for prop_name, type_name in input_bindings.items():
                type_module = None
                for imp in parse_static_imports(content):
                    for _local, exported_name in imp["named"]:
                        if exported_name == type_name:
                            type_module = imp["module"]
                            break
                    if type_module:
                        break

                if not type_module or not type_module.startswith("."):
                    continue

                resolved_type_path = resolve_module_path(path, type_module, known_paths)
                if not resolved_type_path:
                    continue

                type_content = get_content(resolved_type_path)
                if not type_content:
                    continue

                interface_members = extract_interface_members(type_content, type_name)
                if not interface_members:
                    # Not found, unparsable, or has nested types -- skip
                    # rather than risk a false positive (see
                    # extract_interface_members's docstring).
                    continue

                masked_content = _mask_import_statements(content)
                for _accessed_var, member, line_no in find_member_accesses(
                    masked_content, [prop_name]
                ):
                    if member in interface_members:
                        continue
                    suggestion = difflib.get_close_matches(member, list(interface_members), n=1)
                    hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ""
                    issues.append(
                        {
                            "file": path,
                            "issue": (
                                f"Property '{member}' does not exist on type '{type_name}'."
                                f"{hint} (line {line_no})"
                            ),
                            "fix": (
                                f"In {path}, either use an existing field of {type_name} "
                                f"(available: {', '.join(sorted(interface_members))}) instead of "
                                f"'{member}', or add a '{member}' field to the {type_name} "
                                f"interface in {resolved_type_path} if the API actually returns it."
                            ),
                        }
                    )

        # -----------------------------------------------------------------
        # Typed RxJS/Promise callback-parameter member access, e.g.
        # `.subscribe({ next: (response: ExercisesResponse) => {
        #     this.hasNextPage.set(response.hasNextPage); // WRONG: nested
        #     under response.meta.hasNextPage in the real interface
        # }})`
        # This is the exact class of bug in PR #35 (SCRUM-14 attempt #2):
        # the interface itself was correct, but the code assumed a flatter
        # shape than the interface actually declares. Distinct from both
        # the injected-service check (constructor/inject-bound vars) and
        # the @Input() check (component-property-bound vars) above — this
        # covers a local callback parameter's own type annotation.
        # -----------------------------------------------------------------
        masked_content_for_callbacks = _mask_import_statements(content)
        for cb_start, cb_end, param_name, type_name in extract_callback_typed_params(
            masked_content_for_callbacks
        ):
            type_module = resolve_named_import_module(content, type_name)
            if not type_module or not type_module.startswith("."):
                continue

            resolved_type_path = resolve_module_path(path, type_module, known_paths)
            if not resolved_type_path:
                continue

            type_content = get_content(resolved_type_path)
            if not type_content:
                continue

            interface_members = extract_interface_members(type_content, type_name)
            if not interface_members:
                continue

            for _var, member, offset, line_no in find_member_accesses_with_offsets(
                masked_content_for_callbacks, [param_name]
            ):
                if not (cb_start <= offset < cb_end):
                    continue
                if member in interface_members:
                    continue
                suggestion = difflib.get_close_matches(member, list(interface_members), n=1)
                hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ""
                issues.append(
                    {
                        "file": path,
                        "issue": (
                            f"Property '{member}' does not exist on type '{type_name}'."
                            f"{hint} (line {line_no})"
                        ),
                        "fix": (
                            f"In {path}, either use an existing field of {type_name} "
                            f"(available: {', '.join(sorted(interface_members))}) instead of "
                            f"'{member}', or check {resolved_type_path} — the field may be "
                            f"nested under a different property (e.g. inside a 'meta' object) "
                            f"rather than flat on the top-level response."
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
                named_exports_needed = [exported for _local, exported in imp["named"]]
                issues.append(
                    {
                        "file": path,
                        "issue": f"Cannot find module '{module}' or its corresponding type declarations",
                        "fix": (
                            f"Update the import path in {path} to point to the file that actually "
                            f"exists in the repository (the current path '{module}' does not resolve)."
                        ),
                        # These extra keys let the caller distinguish "the
                        # target file doesn't exist at all" (fixable only by
                        # CREATING it) from "wrong content in an existing
                        # file" (fixable by patching in place). A patch to
                        # `path` can never resolve this issue on its own —
                        # there is nothing at `module` to patch.
                        "kind": "MISSING_MODULE",
                        "expectedPath": expected_missing_path(path, module),
                        "requiredExports": named_exports_needed,
                        "importingModule": module,
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
                        "kind": "MISSING_MODULE",
                        "expectedPath": expected_missing_path(path, module),
                        "requiredExports": [dyn["member"]],
                        "importingModule": module,
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

            # Mask import statements first -- same collision risk as the
            # @Input() check above (e.g. a var named to match its import
            # path) applies here too, for the same reason.
            masked_content = _mask_import_statements(content)
            for _accessed_var, member, line_no in find_member_accesses(masked_content, [var_name]):
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
                masked_content, [var_name]
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

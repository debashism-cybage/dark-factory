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

_RESERVED_METHOD_NAMES = {"constructor", "if", "for", "while", "switch", "catch", "else"}


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


def extract_class_members(content: str, class_name: str) -> set[str] | None:
    """
    Extract member names (properties, getters, setters, methods) declared
    directly on a class body via brace-matching + regexes.

    Returns None if the class can't be found or its body can't be matched —
    callers should skip member-existence checks in that case rather than
    risk false positives from a failed/partial parse.
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

    body = content[start + 1 : end]
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


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

    def get_content(path: str) -> str | None:
        if path not in content_cache:
            content_cache[path] = fetch_content(path)
        return content_cache[path]

    for path, content in files.items():
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

    return issues

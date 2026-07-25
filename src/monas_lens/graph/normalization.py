"""Deterministic language-aware normalization for unresolved syntax facts."""

from __future__ import annotations

import posixpath
import re
from pathlib import PurePosixPath

from monas_lens.graph.contracts import (
    NormalizedFact,
    NormalizedTarget,
    RelationKind,
    TargetKind,
)
from monas_lens.indexing.contracts import FactKind, Language

_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_CONFIGURATION_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,127}")
_JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")


def normalize_fact(
    language: Language,
    kind: FactKind,
    target_text: str,
    source_path: str,
) -> NormalizedFact:
    raw_target = target_text.strip()
    if kind is FactKind.IMPORT:
        return _normalize_import(language, raw_target, source_path)
    if kind is FactKind.CALL:
        return _normalize_symbol_target(RelationKind.CALLS, raw_target)
    if kind is FactKind.INHERITS:
        return _normalize_type_targets(RelationKind.INHERITS, raw_target)
    if kind is FactKind.IMPLEMENTS:
        return _normalize_type_targets(RelationKind.IMPLEMENTS, raw_target)
    if kind is FactKind.CONFIGURATION:
        return _normalize_configuration(raw_target)
    if kind in {FactKind.EXPORT, FactKind.DECORATOR, FactKind.ROUTE, FactKind.TESTS}:
        return NormalizedFact(relation_kind=None, targets=())
    return _unsupported("unsupported_fact_kind")


def module_path_candidates(language: Language, source_path: str, module: str) -> tuple[str, ...]:
    if language is Language.PYTHON:
        return _python_module_candidates(source_path, module)
    if language in {Language.JAVASCRIPT, Language.TYPESCRIPT, Language.TSX}:
        return _javascript_module_candidates(source_path, module)
    if language is Language.DART:
        return _dart_module_candidates(source_path, module)
    return ()


def _normalize_import(
    language: Language,
    target_text: str,
    source_path: str,
) -> NormalizedFact:
    if language is Language.PYTHON:
        targets = _python_import_targets(target_text, source_path)
    elif language in {Language.JAVASCRIPT, Language.TYPESCRIPT, Language.TSX}:
        targets = _javascript_import_targets(language, target_text, source_path)
    elif language is Language.DART:
        targets = _dart_import_targets(target_text, source_path)
    else:
        targets = ()
    if not targets:
        return _unsupported("unsupported_import_syntax")
    return NormalizedFact(RelationKind.IMPORTS, _deduplicate_targets(targets))


def _python_import_targets(
    target_text: str,
    source_path: str,
) -> tuple[NormalizedTarget, ...]:
    direct = re.fullmatch(r"import\s+(.+)", target_text, flags=re.DOTALL)
    if direct is not None:
        targets: list[NormalizedTarget] = []
        for entry in _split_comma_list(direct.group(1)):
            matched = re.fullmatch(
                r"([A-Za-z_][A-Za-z0-9_.]*)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?",
                entry,
            )
            if matched is None:
                continue
            module, alias = matched.groups()
            targets.append(
                _module_target(
                    Language.PYTHON,
                    source_path,
                    module,
                    alias=alias or module.split(".")[0],
                )
            )
        return tuple(targets)

    imported = re.fullmatch(
        r"from\s+([.A-Za-z_][A-Za-z0-9_.]*)\s+import\s+(.+)",
        target_text,
        flags=re.DOTALL,
    )
    if imported is None:
        return ()
    module = imported.group(1)
    names = imported.group(2).strip().removeprefix("(").removesuffix(")")
    targets = []
    for entry in _split_comma_list(names):
        matched = re.fullmatch(
            r"([A-Za-z_][A-Za-z0-9_]*|\*)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?",
            entry,
        )
        if matched is None:
            continue
        imported_name, alias = matched.groups()
        targets.append(
            _module_target(
                Language.PYTHON,
                source_path,
                module,
                imported_name=None if imported_name == "*" else imported_name,
                alias=alias or (None if imported_name == "*" else imported_name),
            )
        )
    return tuple(targets)


def _javascript_import_targets(
    language: Language,
    target_text: str,
    source_path: str,
) -> tuple[NormalizedTarget, ...]:
    require_match = re.search(
        r"(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*require\(\s*"
        r"['\"]([^'\"]+)['\"]\s*\)",
        target_text,
    )
    if require_match is not None:
        alias, module = require_match.groups()
        return (_module_target(language, source_path, module, alias=alias),)

    module_match = re.search(r"\bfrom\s+['\"]([^'\"]+)['\"]", target_text)
    if module_match is None:
        module_match = re.fullmatch(r"\s*import\s+['\"]([^'\"]+)['\"]\s*;?\s*", target_text)
        if module_match is None:
            return ()
        return (_module_target(language, source_path, module_match.group(1)),)

    module = module_match.group(1)
    clause = target_text[target_text.find("import") + len("import") : module_match.start()].strip()
    bindings: list[tuple[str | None, str | None]] = []

    namespace = re.search(r"\*\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)", clause)
    if namespace is not None:
        bindings.append((None, namespace.group(1)))

    named = re.search(r"\{([^}]*)\}", clause, flags=re.DOTALL)
    if named is not None:
        for entry in _split_comma_list(named.group(1)):
            matched = re.fullmatch(
                r"([A-Za-z_$][A-Za-z0-9_$]*)"
                r"(?:\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*))?",
                entry,
            )
            if matched is not None:
                imported_name, alias = matched.groups()
                bindings.append((imported_name, alias or imported_name))

    default_clause = re.sub(r"\{[^}]*\}", "", clause)
    default_clause = re.sub(r"\*\s+as\s+[A-Za-z_$][A-Za-z0-9_$]*", "", default_clause)
    default_name = default_clause.strip(" ,")
    if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", default_name):
        bindings.append((default_name, default_name))

    if not bindings:
        bindings.append((None, None))
    return tuple(
        _module_target(
            language,
            source_path,
            module,
            imported_name=imported_name,
            alias=alias,
        )
        for imported_name, alias in bindings
    )


def _dart_import_targets(
    target_text: str,
    source_path: str,
) -> tuple[NormalizedTarget, ...]:
    matched = re.search(
        r"\bimport\s+['\"]([^'\"]+)['\"](?:\s+deferred)?"
        r"(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?",
        target_text,
    )
    if matched is None:
        return ()
    module, alias = matched.groups()
    return (_module_target(Language.DART, source_path, module, alias=alias),)


def _normalize_symbol_target(
    relation_kind: RelationKind,
    target_text: str,
) -> NormalizedFact:
    compact = re.sub(r"\([^()]*\)", "", target_text)
    compact = compact.replace("?.", ".").replace("::", ".").strip()
    identifiers = _IDENTIFIER.findall(compact)
    if not identifiers:
        return _unsupported("unsupported_symbol_target")
    value = identifiers[-1]
    qualifier = identifiers[-2] if len(identifiers) > 1 else None
    return NormalizedFact(
        relation_kind,
        (
            NormalizedTarget(
                TargetKind.SYMBOL,
                value=value,
                qualifier=qualifier,
            ),
        ),
    )


def _normalize_type_targets(
    relation_kind: RelationKind,
    target_text: str,
) -> NormalizedFact:
    selected = target_text.strip()
    values: list[str] = []
    if selected.startswith("(") and selected.endswith(")"):
        values.extend(_split_comma_list(selected[1:-1]))
    else:
        keyword = "implements" if relation_kind is RelationKind.IMPLEMENTS else "extends"
        for matched in re.finditer(
            rf"\b{keyword}\s+(.+?)(?=\s+\b(?:with|implements|extends)\b|$)",
            selected,
        ):
            values.extend(_split_comma_list(matched.group(1)))
        if relation_kind is RelationKind.INHERITS:
            for matched in re.finditer(
                r"\bwith\s+(.+?)(?=\s+\b(?:implements|extends)\b|$)",
                selected,
            ):
                values.extend(_split_comma_list(matched.group(1)))
        if not values and re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$.<>?]*", selected):
            values.append(selected)

    targets: list[NormalizedTarget] = []
    for value in values:
        identifiers = _IDENTIFIER.findall(re.sub(r"<.*>", "", value))
        if not identifiers:
            continue
        name = identifiers[-1]
        qualifier = identifiers[-2] if len(identifiers) > 1 else None
        targets.append(NormalizedTarget(TargetKind.SYMBOL, name, qualifier=qualifier))
    if not targets:
        return _unsupported("unsupported_type_target")
    return NormalizedFact(relation_kind, _deduplicate_targets(tuple(targets)))


def _normalize_configuration(target_text: str) -> NormalizedFact:
    if _CONFIGURATION_KEY.fullmatch(target_text) is None:
        return _unsupported("unsupported_configuration_key")
    return NormalizedFact(
        RelationKind.CONFIGURED_BY,
        (NormalizedTarget(TargetKind.CONFIGURATION, target_text),),
    )


def _module_target(
    language: Language,
    source_path: str,
    module: str,
    *,
    imported_name: str | None = None,
    alias: str | None = None,
) -> NormalizedTarget:
    return NormalizedTarget(
        TargetKind.MODULE,
        value=module,
        alias=alias,
        imported_name=imported_name,
        candidate_paths=module_path_candidates(language, source_path, module),
    )


def _python_module_candidates(source_path: str, module: str) -> tuple[str, ...]:
    source = PurePosixPath(source_path)
    leading_dots = len(module) - len(module.lstrip("."))
    module_name = module.lstrip(".")
    if leading_dots:
        base_parts = list(source.parent.parts)
        levels_up = leading_dots - 1
        if levels_up > len(base_parts):
            return ()
        base_parts = base_parts[: len(base_parts) - levels_up]
        module_parts = [*base_parts, *module_name.split(".")] if module_name else base_parts
    else:
        module_parts = module_name.split(".")
    if not module_parts:
        return ()
    base = "/".join(part for part in module_parts if part)
    return _deduplicate((f"{base}.py", f"{base}/__init__.py"))


def _javascript_module_candidates(source_path: str, module: str) -> tuple[str, ...]:
    if not module.startswith(("./", "../")):
        return ()
    joined = _relative_module_path(source_path, module)
    suffix = PurePosixPath(joined).suffix
    if suffix in _JS_EXTENSIONS:
        return (joined,)
    return _deduplicate(
        (
            *(f"{joined}{extension}" for extension in _JS_EXTENSIONS),
            *(f"{joined}/index{extension}" for extension in _JS_EXTENSIONS),
        )
    )


def _dart_module_candidates(source_path: str, module: str) -> tuple[str, ...]:
    if module.startswith("dart:"):
        return ()
    if module.startswith("package:"):
        package_path = module.removeprefix("package:")
        _, separator, relative = package_path.partition("/")
        return (f"lib/{relative}",) if separator and relative else ()
    return (_relative_module_path(source_path, module),)


def _relative_module_path(source_path: str, module: str) -> str:
    source_dir = PurePosixPath(source_path).parent.as_posix()
    joined = posixpath.normpath(posixpath.join(source_dir, module))
    return joined.removeprefix("./")


def _split_comma_list(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", " ").split(",") if item.strip()]


def _deduplicate_targets(
    targets: tuple[NormalizedTarget, ...],
) -> tuple[NormalizedTarget, ...]:
    return tuple(dict.fromkeys(targets))


def _deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _unsupported(reason: str) -> NormalizedFact:
    return NormalizedFact(
        relation_kind=None,
        targets=(),
        supported=False,
        diagnostic=reason,
    )

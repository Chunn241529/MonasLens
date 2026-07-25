import pytest

from monas_lens.graph.contracts import RelationKind, TargetKind
from monas_lens.graph.normalization import normalize_fact
from monas_lens.indexing.contracts import FactKind, Language


@pytest.mark.parametrize(
    ("language", "source_path", "target_text", "expected"),
    [
        (
            Language.PYTHON,
            "pkg/feature.py",
            "from .service import Service as Alias",
            (".service", "pkg/service.py", "Service", "Alias"),
        ),
        (
            Language.JAVASCRIPT,
            "src/feature.js",
            "import { Service as Alias } from './service.js';",
            ("./service.js", "src/service.js", "Service", "Alias"),
        ),
        (
            Language.TYPESCRIPT,
            "src/feature.ts",
            "import * as service from '../shared/service';",
            ("../shared/service", "shared/service.ts", None, "service"),
        ),
        (
            Language.TSX,
            "src/view.tsx",
            "import { Widget } from './widget';",
            ("./widget", "src/widget.tsx", "Widget", "Widget"),
        ),
        (
            Language.DART,
            "lib/feature.dart",
            "import 'service.dart' as service;",
            ("service.dart", "lib/service.dart", None, "service"),
        ),
    ],
)
def test_import_normalization_golden_cases(
    language: Language,
    source_path: str,
    target_text: str,
    expected: tuple[str, str, str | None, str | None],
) -> None:
    normalized = normalize_fact(
        language,
        FactKind.IMPORT,
        target_text,
        source_path,
    )

    assert normalized.supported
    assert normalized.relation_kind is RelationKind.IMPORTS
    target = normalized.targets[0]
    assert target.kind is TargetKind.MODULE
    assert target.value == expected[0]
    assert expected[1] in target.candidate_paths
    assert target.imported_name == expected[2]
    assert target.alias == expected[3]


@pytest.mark.parametrize(
    ("target_text", "value", "qualifier"),
    [
        ("Alias().execute", "execute", "Alias"),
        ("service?.run", "run", "service"),
        (".toString", "toString", None),
        ("plain_call", "plain_call", None),
    ],
)
def test_call_normalization_preserves_leaf_and_qualifier(
    target_text: str,
    value: str,
    qualifier: str | None,
) -> None:
    normalized = normalize_fact(
        Language.PYTHON,
        FactKind.CALL,
        target_text,
        "feature.py",
    )

    assert normalized.relation_kind is RelationKind.CALLS
    assert normalized.targets[0].value == value
    assert normalized.targets[0].qualifier == qualifier


@pytest.mark.parametrize(
    ("language", "kind", "target_text", "expected"),
    [
        (Language.PYTHON, FactKind.INHERITS, "(Base, Mixin)", {"Base", "Mixin"}),
        (
            Language.TYPESCRIPT,
            FactKind.INHERITS,
            "extends Base implements Contract",
            {"Base"},
        ),
        (
            Language.TYPESCRIPT,
            FactKind.IMPLEMENTS,
            "implements Contract, Auditable",
            {"Contract", "Auditable"},
        ),
        (
            Language.DART,
            FactKind.INHERITS,
            "extends Base with Mixin",
            {"Base", "Mixin"},
        ),
    ],
)
def test_type_normalization_handles_composite_facts(
    language: Language,
    kind: FactKind,
    target_text: str,
    expected: set[str],
) -> None:
    normalized = normalize_fact(language, kind, target_text, "feature.ts")

    assert {target.value for target in normalized.targets} == expected


def test_configuration_and_unsupported_targets_are_explicit() -> None:
    configuration = normalize_fact(
        Language.PYTHON,
        FactKind.CONFIGURATION,
        "API_URL",
        "service.py",
    )
    unsupported = normalize_fact(
        Language.DART,
        FactKind.CALL,
        "()",
        "service.dart",
    )

    assert configuration.targets[0].kind is TargetKind.CONFIGURATION
    assert configuration.relation_kind is RelationKind.CONFIGURED_BY
    assert not unsupported.supported
    assert unsupported.diagnostic == "unsupported_symbol_target"

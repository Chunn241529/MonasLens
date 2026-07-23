from collections.abc import Iterable

import pytest

from monas_lens.indexing.contracts import (
    ExtractedSymbol,
    FactKind,
    Language,
    SymbolKind,
)
from monas_lens.parsing.registry import ParserRegistry


def symbol_names(result_symbols: Iterable[ExtractedSymbol]) -> set[str]:
    return {symbol.name for symbol in result_symbols}


def test_python_extraction_is_stable_across_unrelated_line_shifts() -> None:
    registry = ParserRegistry()
    source = b'''
from pathlib import Path

class Service(Base):
    """Service docs."""

    def run(self, value: int) -> str:
        return str(value)

def test_service() -> None:
    Service().run(1)
'''

    first = registry.extract(Language.PYTHON, "service.py", source)
    shifted = registry.extract(
        Language.PYTHON,
        "service.py",
        b"# unrelated comment\n\n" + source,
    )

    assert not first.has_errors
    assert symbol_names(first.symbols) == {"Service", "run", "test_service"}
    service = next(symbol for symbol in first.symbols if symbol.name == "Service")
    method = next(symbol for symbol in first.symbols if symbol.name == "run")
    test = next(symbol for symbol in first.symbols if symbol.name == "test_service")
    assert service.kind is SymbolKind.CLASS
    assert method.kind is SymbolKind.METHOD
    assert method.qualified_name == "Service.run"
    assert test.kind is SymbolKind.TEST
    assert {symbol.id for symbol in first.symbols} == {symbol.id for symbol in shifted.symbols}
    assert any(fact.kind is FactKind.IMPORT for fact in first.facts)
    assert any(fact.kind is FactKind.CALL for fact in first.facts)
    assert first.chunks


@pytest.mark.parametrize(
    ("language", "source", "expected_names"),
    [
        (
            Language.JAVASCRIPT,
            b"export class Service { run(value) { return value; } }\n",
            {"Service", "run"},
        ),
        (
            Language.TYPESCRIPT,
            b"export interface Service { run(value: number): string; }\n"
            b"export const create = (value: number): string => String(value);\n",
            {"Service", "run", "create"},
        ),
        (
            Language.TSX,
            b"export const Component = () => <div />;\n",
            {"Component"},
        ),
        (
            Language.DART,
            b"class Service { String run(int value) => value.toString(); }\n",
            {"Service", "run"},
        ),
    ],
)
def test_supported_language_extraction(
    language: Language,
    source: bytes,
    expected_names: set[str],
) -> None:
    result = ParserRegistry().extract(language, f"fixture.{language.value}", source)

    assert not result.has_errors
    assert expected_names <= symbol_names(result.symbols)
    assert all(symbol.source_range.end_byte <= len(source) for symbol in result.symbols)


def test_syntax_errors_are_reported_without_crashing() -> None:
    result = ParserRegistry().extract(
        Language.PYTHON,
        "broken.py",
        b"def broken(:\n    pass\n",
    )

    assert result.has_errors
    assert result.error_node_count > 0


def test_route_and_test_facts_are_classified() -> None:
    source = b"test('works', () => {});\napp.get('/items', handler);\n"

    result = ParserRegistry().extract(
        Language.JAVASCRIPT,
        "routes.js",
        source,
    )

    assert {fact.kind for fact in result.facts} >= {
        FactKind.TESTS,
        FactKind.ROUTE,
    }


def test_dart_method_body_facts_belong_to_method() -> None:
    result = ParserRegistry().extract(
        Language.DART,
        "service.dart",
        b"class Service { String run(int value) => value.toString(); }\n",
    )
    method = next(symbol for symbol in result.symbols if symbol.name == "run")
    calls = [fact for fact in result.facts if fact.kind is FactKind.CALL]

    assert calls
    assert all(fact.source_symbol_id == method.id for fact in calls)


def test_parser_diagnostics_cover_all_initial_languages() -> None:
    diagnostics = ParserRegistry().diagnostics()

    assert diagnostics == {
        "python": True,
        "javascript": True,
        "typescript": True,
        "tsx": True,
        "dart": True,
    }

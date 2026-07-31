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
    source = b"test('works', () => handler());\napp.get('/items', handler);\n"

    result = ParserRegistry().extract(
        Language.JAVASCRIPT,
        "routes.js",
        source,
    )

    assert {fact.kind for fact in result.facts} >= {
        FactKind.TESTS,
        FactKind.ROUTE,
    }
    test_symbol = next(symbol for symbol in result.symbols if symbol.kind is SymbolKind.TEST)
    nested_calls = [
        fact
        for fact in result.facts
        if fact.kind is FactKind.CALL and fact.target_text == "handler"
    ]
    assert test_symbol.name == "works"
    assert all(fact.source_symbol_id == test_symbol.id for fact in nested_calls)


@pytest.mark.parametrize(
    ("language", "source", "expected_keys"),
    [
        (
            Language.PYTHON,
            b"def load():\n    return os.getenv('API_URL')\n",
            {"API_URL"},
        ),
        (
            Language.JAVASCRIPT,
            b"const load = () => process.env.API_URL;\n",
            {"API_URL"},
        ),
        (
            Language.TYPESCRIPT,
            b"const load = (): string => config.get('API_URL');\n",
            {"API_URL"},
        ),
        (
            Language.TSX,
            b"export const View = () => <div>{process.env.API_URL}</div>;\n",
            {"API_URL"},
        ),
        (
            Language.DART,
            b"String load() => String.fromEnvironment('API_URL');\n",
            {"API_URL"},
        ),
    ],
)
def test_configuration_keys_are_extracted_without_values(
    language: Language,
    source: bytes,
    expected_keys: set[str],
) -> None:
    result = ParserRegistry().extract(language, f"config.{language.value}", source)
    configuration_facts = [fact for fact in result.facts if fact.kind is FactKind.CONFIGURATION]

    assert {fact.target_text for fact in configuration_facts} == expected_keys
    assert all(fact.metadata == {"configuration_key": True} for fact in configuration_facts)
    assert all(fact.source_symbol_id is not None for fact in configuration_facts)


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


def test_explicit_receiver_types_are_added_to_call_fact_metadata() -> None:
    result = ParserRegistry().extract(
        Language.PYTHON,
        "controller.py",
        b"class Service:\n"
        b"    def run(self) -> None:\n"
        b"        pass\n\n"
        b"def execute() -> None:\n"
        b"    service = Service()\n"
        b"    service.run()\n",
    )

    run_call = next(
        fact
        for fact in result.facts
        if fact.kind is FactKind.CALL and fact.target_text == "service.run"
    )

    assert run_call.metadata == {"receiver_type": "Service"}


def test_conflicting_receiver_types_remain_unresolved_metadata() -> None:
    result = ParserRegistry().extract(
        Language.PYTHON,
        "controller.py",
        b"def execute(flag: bool) -> None:\n"
        b"    service = FirstService()\n"
        b"    if flag:\n"
        b"        service = SecondService()\n"
        b"    service.run()\n",
    )

    run_call = next(
        fact
        for fact in result.facts
        if fact.kind is FactKind.CALL and fact.target_text == "service.run"
    )

    assert run_call.metadata == {}


def test_python_route_parameter_emits_schema_fact() -> None:
    result = ParserRegistry().extract(
        Language.PYTHON,
        "routes.py",
        b"@app.post('/users')\n"
        b"def create_user(payload: UserCreate) -> str:\n"
        b"    return payload.name\n",
    )
    handler = next(symbol for symbol in result.symbols if symbol.name == "create_user")
    schema = next(fact for fact in result.facts if fact.kind is FactKind.SCHEMA)

    assert schema.target_text == "UserCreate"
    assert schema.source_symbol_id == handler.id


def test_go_extracts_types_functions_methods_imports_calls_and_tests() -> None:
    source = b"""package service

import "fmt"

type Service struct{}

func NewService() *Service {
    return &Service{}
}

func (service *Service) Run(value int) string {
    return fmt.Sprint(value)
}

func TestService(t *testing.T) {
    NewService().Run(1)
}
"""

    result = ParserRegistry().extract(Language.GO, "service_test.go", source)

    assert not result.has_errors
    symbols = {symbol.name: symbol for symbol in result.symbols}
    assert {name: symbol.kind for name, symbol in symbols.items()} == {
        "Service": SymbolKind.CLASS,
        "NewService": SymbolKind.FUNCTION,
        "Run": SymbolKind.METHOD,
        "TestService": SymbolKind.TEST,
    }
    assert symbols["Run"].parameters == ("value int",)
    assert symbols["Run"].return_type == "string"
    assert symbols["TestService"].metadata["is_test"] is True
    assert any(
        fact.kind is FactKind.IMPORT and fact.target_text == '"fmt"' for fact in result.facts
    )
    call_targets = {fact.target_text for fact in result.facts if fact.kind is FactKind.CALL}
    assert {"fmt.Sprint", "NewService", "NewService().Run"} <= call_targets
    assert all(symbol.source_range.end_byte <= len(source) for symbol in result.symbols)


def test_parser_diagnostics_cover_all_supported_languages() -> None:
    diagnostics = ParserRegistry().diagnostics()

    assert diagnostics == {
        "python": True,
        "javascript": True,
        "typescript": True,
        "tsx": True,
        "dart": True,
        "go": True,
    }

"""Lazy parser adapter registry."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from tree_sitter import Parser
from tree_sitter_language_pack import SupportedLanguage, get_parser

from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.indexing.contracts import ExtractionResult, Language
from monas_lens.parsing.base import TreeSitterAdapter
from monas_lens.parsing.languages import (
    DartAdapter,
    GoAdapter,
    JavaScriptAdapter,
    PythonAdapter,
    TsxAdapter,
    TypeScriptAdapter,
)

_ADAPTERS: dict[Language, type[TreeSitterAdapter]] = {
    Language.PYTHON: PythonAdapter,
    Language.JAVASCRIPT: JavaScriptAdapter,
    Language.TYPESCRIPT: TypeScriptAdapter,
    Language.TSX: TsxAdapter,
    Language.DART: DartAdapter,
    Language.GO: GoAdapter,
}


def _default_parser_factory(language_name: str) -> Parser:
    return get_parser(cast(SupportedLanguage, language_name))


class ParserRegistry:
    """Load installed parsers lazily and isolate package-specific APIs."""

    def __init__(
        self,
        parser_factory: Callable[[str], Parser] = _default_parser_factory,
    ) -> None:
        self._parser_factory = parser_factory
        self._adapters: dict[Language, TreeSitterAdapter] = {}

    def extract(
        self,
        language: Language,
        relative_path: str,
        source: bytes,
    ) -> ExtractionResult:
        return self.adapter(language).extract(relative_path, source)

    def adapter(self, language: Language) -> TreeSitterAdapter:
        cached = self._adapters.get(language)
        if cached is not None:
            return cached
        adapter_type = _ADAPTERS.get(language)
        if adapter_type is None:
            raise MonasLensError(
                ErrorCode.PARSER_UNAVAILABLE,
                "No structural parser is configured for this language.",
                details={"language": language.value},
            )
        try:
            parser = self._parser_factory(adapter_type.parser_name)
        except Exception as exc:
            raise MonasLensError(
                ErrorCode.PARSER_UNAVAILABLE,
                "The installed Tree-sitter grammar could not be loaded.",
                details={"language": language.value},
            ) from exc
        adapter = adapter_type(parser)
        self._adapters[language] = adapter
        return adapter

    def diagnostics(self) -> dict[str, bool]:
        return {language.value: self._parser_available(language) for language in _ADAPTERS}

    def _parser_available(self, language: Language) -> bool:
        try:
            self.adapter(language)
        except MonasLensError:
            return False
        return True

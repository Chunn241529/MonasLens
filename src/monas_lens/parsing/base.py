"""Shared Tree-sitter traversal and extraction primitives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from tree_sitter import Node, Parser

from monas_lens.indexing.contracts import (
    ChunkKind,
    ExtractedChunk,
    ExtractedSymbol,
    ExtractionResult,
    FactKind,
    Language,
    SourceRange,
    SymbolKind,
    SyntaxFact,
)
from monas_lens.indexing.identity import stable_id

_CLASS_KINDS = {
    SymbolKind.CLASS,
    SymbolKind.INTERFACE,
    SymbolKind.MIXIN,
    SymbolKind.EXTENSION,
}


@dataclass(frozen=True, slots=True)
class ParentSymbol:
    id: str
    kind: SymbolKind
    qualified_name: str


class TreeSitterAdapter(ABC):
    language: Language
    parser_name: str
    import_node_types: frozenset[str] = frozenset()
    export_node_types: frozenset[str] = frozenset()
    call_node_types: frozenset[str] = frozenset()
    inheritance_node_types: frozenset[str] = frozenset()
    decorator_node_types: frozenset[str] = frozenset()

    def __init__(self, parser: Parser) -> None:
        self._parser = parser

    def extract(self, relative_path: str, source: bytes) -> ExtractionResult:
        tree = self._parser.parse(source)
        symbols: list[ExtractedSymbol] = []
        facts: list[SyntaxFact] = []
        seen_symbol_ids: dict[str, int] = {}
        consumed_nodes: set[tuple[int, int, str]] = set()
        error_node_count = 0

        def visit(node: Node, parent_symbol: ParentSymbol | None) -> None:
            nonlocal error_node_count
            if node.is_error or node.is_missing:
                error_node_count += 1

            symbol = self._extract_symbol(
                node,
                source,
                relative_path,
                parent_symbol,
                seen_symbol_ids,
            )
            current_parent = parent_symbol
            if symbol is not None:
                symbols.append(symbol)
                current_parent = ParentSymbol(
                    id=symbol.id,
                    kind=symbol.kind,
                    qualified_name=symbol.qualified_name,
                )

            fact = self._extract_fact(
                node,
                source,
                relative_path,
                current_parent,
            )
            if fact is not None:
                facts.append(fact)

            associated_body = self.associated_body_node(node)
            if associated_body is not None:
                visit(associated_body, current_parent)
                consumed_nodes.add(_node_key(associated_body))

            for child in node.children:
                if _node_key(child) in consumed_nodes:
                    continue
                visit(child, current_parent)

        visit(tree.root_node, None)
        symbols.sort(key=lambda item: (item.source_range.start_byte, item.id))
        facts.sort(key=lambda item: (item.source_range.start_byte, item.id))
        chunks = build_chunks(relative_path, source, symbols)
        return ExtractionResult(
            relative_path=relative_path,
            language=self.language,
            symbols=tuple(symbols),
            facts=tuple(facts),
            chunks=chunks,
            has_errors=tree.root_node.has_error,
            error_node_count=error_node_count,
        )

    @abstractmethod
    def classify_symbol(
        self, node: Node, source: bytes, parent: ParentSymbol | None
    ) -> SymbolKind | None:
        raise NotImplementedError

    def symbol_name_node(self, node: Node, source: bytes) -> Node | None:
        return node.child_by_field_name("name")

    def parameters_node(self, node: Node) -> Node | None:
        parameters = node.child_by_field_name("parameters")
        if parameters is not None:
            return parameters
        return first_named_descendant(node, {"formal_parameter_list"})

    def return_type_node(self, node: Node) -> Node | None:
        return node.child_by_field_name("return_type")

    def symbol_metadata(
        self,
        node: Node,
        source: bytes,
        kind: SymbolKind,
        name: str,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if name.startswith(("test_", "test")) or name.endswith(("Test", "Tests")):
            metadata["is_test"] = True
        return metadata

    def symbol_source_range(self, node: Node) -> SourceRange:
        return source_range(node)

    def associated_body_node(self, node: Node) -> Node | None:
        return None

    def docstring(self, node: Node, source: bytes) -> str | None:
        return None

    def signature(self, node: Node, source: bytes) -> str:
        body = node.child_by_field_name("body")
        end_byte = body.start_byte if body is not None else node.end_byte
        signature = node_text(node, source, end_byte=end_byte).strip()
        return " ".join(signature.split())

    def fact_kind(self, node: Node, source: bytes) -> FactKind | None:
        if node.type in self.import_node_types:
            return FactKind.IMPORT
        if node.type in self.export_node_types:
            return FactKind.EXPORT
        if node.type in self.call_node_types:
            return FactKind.CALL
        if node.type in self.inheritance_node_types:
            return FactKind.INHERITS
        if node.type in self.decorator_node_types:
            return FactKind.DECORATOR
        return None

    def fact_target_node(self, node: Node, kind: FactKind) -> Node:
        if kind is FactKind.CALL:
            return node.child_by_field_name("function") or node.child_by_field_name("name") or node
        return node

    def _extract_symbol(
        self,
        node: Node,
        source: bytes,
        relative_path: str,
        parent: ParentSymbol | None,
        seen_symbol_ids: dict[str, int],
    ) -> ExtractedSymbol | None:
        kind = self.classify_symbol(node, source, parent)
        if kind is None:
            return None
        name_node = self.symbol_name_node(node, source)
        if name_node is None:
            return None
        name = node_text(name_node, source).strip()
        if not name:
            return None
        qualified_name = f"{parent.qualified_name}.{name}" if parent else name
        signature = self.signature(node, source)
        base_id = stable_id(
            "symbol",
            relative_path,
            self.language.value,
            kind.value,
            qualified_name,
            signature,
        )
        occurrence = seen_symbol_ids.get(base_id, 0)
        seen_symbol_ids[base_id] = occurrence + 1
        symbol_id = base_id if occurrence == 0 else stable_id(base_id, occurrence)
        parameters_node = self.parameters_node(node)
        parameters = (
            tuple(node_text(child, source).strip() for child in parameters_node.named_children)
            if parameters_node is not None
            else ()
        )
        return_type_node = self.return_type_node(node)
        metadata = self.symbol_metadata(node, source, kind, name)
        if metadata.get("is_test"):
            kind = SymbolKind.TEST
        return ExtractedSymbol(
            id=symbol_id,
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            signature=signature,
            parameters=parameters,
            return_type=(
                node_text(return_type_node, source).strip()
                if return_type_node is not None
                else None
            ),
            docstring=self.docstring(node, source),
            source_range=self.symbol_source_range(node),
            metadata=metadata,
        )

    def _extract_fact(
        self,
        node: Node,
        source: bytes,
        relative_path: str,
        parent: ParentSymbol | None,
    ) -> SyntaxFact | None:
        kind = self.fact_kind(node, source)
        if kind is None:
            return None
        target_node = self.fact_target_node(node, kind)
        target_text = node_text(target_node, source).strip()
        fact_id = stable_id(
            "fact",
            relative_path,
            kind.value,
            parent.id if parent else "",
            target_text,
            node.start_byte,
        )
        return SyntaxFact(
            id=fact_id,
            kind=kind,
            target_text=target_text,
            source_range=source_range(node),
            source_symbol_id=parent.id if parent else None,
        )

    @staticmethod
    def is_method(parent: ParentSymbol | None) -> bool:
        return parent is not None and parent.kind in _CLASS_KINDS


def source_range(node: Node) -> SourceRange:
    return SourceRange(
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        start_column=node.start_point.column,
        end_column=node.end_point.column,
    )


def node_text(node: Node, source: bytes, *, end_byte: int | None = None) -> str:
    selected_end = node.end_byte if end_byte is None else end_byte
    return source[node.start_byte : selected_end].decode("utf-8", errors="replace")


def first_named_descendant(node: Node, node_types: set[str]) -> Node | None:
    for child in node.named_children:
        if child.type in node_types:
            return child
        nested = first_named_descendant(child, node_types)
        if nested is not None:
            return nested
    return None


def _node_key(node: Node) -> tuple[int, int, str]:
    return (node.start_byte, node.end_byte, node.type)


def build_chunks(
    relative_path: str,
    source: bytes,
    symbols: list[ExtractedSymbol],
    *,
    max_class_bytes: int = 20_000,
) -> tuple[ExtractedChunk, ...]:
    chunks: list[ExtractedChunk] = []
    seen_hashes: set[str] = set()
    for symbol in symbols:
        if symbol.kind in {
            SymbolKind.FUNCTION,
            SymbolKind.METHOD,
            SymbolKind.CONSTRUCTOR,
            SymbolKind.TEST,
        }:
            chunk_kind = (
                ChunkKind.TEST
                if symbol.kind is SymbolKind.TEST
                else (
                    ChunkKind.METHOD
                    if symbol.kind in {SymbolKind.METHOD, SymbolKind.CONSTRUCTOR}
                    else ChunkKind.FUNCTION
                )
            )
        elif symbol.kind in _CLASS_KINDS and (
            symbol.source_range.end_byte - symbol.source_range.start_byte <= max_class_bytes
        ):
            chunk_kind = ChunkKind.CLASS
        else:
            continue
        text = source[symbol.source_range.start_byte : symbol.source_range.end_byte].decode(
            "utf-8", errors="replace"
        )
        content_hash = sha256(text.encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        chunks.append(
            ExtractedChunk(
                id=stable_id("chunk", relative_path, symbol.id, content_hash),
                kind=chunk_kind,
                content_hash=content_hash,
                source_text=text,
                source_range=symbol.source_range,
                symbol_id=symbol.id,
            )
        )

    summary_lines = [
        f"{symbol.kind.value} {symbol.qualified_name}: {symbol.signature}"
        for symbol in symbols
        if "." not in symbol.qualified_name
    ]
    if summary_lines:
        summary = "\n".join(summary_lines)
        content_hash = sha256(summary.encode("utf-8")).hexdigest()
        file_range = SourceRange(
            start_byte=0,
            end_byte=len(source),
            start_line=1,
            end_line=source.count(b"\n") + 1,
            start_column=0,
            end_column=0,
        )
        chunks.append(
            ExtractedChunk(
                id=stable_id("module-summary", relative_path, content_hash),
                kind=ChunkKind.MODULE_SUMMARY,
                content_hash=content_hash,
                source_text=summary,
                source_range=file_range,
                metadata={"generated": True},
            )
        )
    return tuple(chunks)

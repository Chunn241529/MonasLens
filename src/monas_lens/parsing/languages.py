"""Language-specific Tree-sitter structural rules."""

from __future__ import annotations

from typing import Any

from tree_sitter import Node

from monas_lens.indexing.contracts import FactKind, Language, SourceRange, SymbolKind
from monas_lens.parsing.base import (
    ParentSymbol,
    TreeSitterAdapter,
    first_named_descendant,
    node_text,
)


class PythonAdapter(TreeSitterAdapter):
    language = Language.PYTHON
    parser_name = "python"
    import_node_types = frozenset({"import_statement", "import_from_statement"})
    call_node_types = frozenset({"call"})
    inheritance_node_types = frozenset({"argument_list"})
    decorator_node_types = frozenset({"decorator"})

    def classify_symbol(
        self, node: Node, source: bytes, parent: ParentSymbol | None
    ) -> SymbolKind | None:
        if node.type == "class_definition":
            return SymbolKind.CLASS
        if node.type == "function_definition":
            return SymbolKind.METHOD if self.is_method(parent) else SymbolKind.FUNCTION
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier":
                name = node_text(left, source)
                if name.isupper():
                    return SymbolKind.CONSTANT
        return None

    def symbol_name_node(self, node: Node, source: bytes) -> Node | None:
        if node.type == "assignment":
            return node.child_by_field_name("left")
        return super().symbol_name_node(node, source)

    def return_type_node(self, node: Node) -> Node | None:
        return node.child_by_field_name("return_type")

    def docstring(self, node: Node, source: bytes) -> str | None:
        body = node.child_by_field_name("body")
        if body is None or not body.named_children:
            return None
        statement = body.named_children[0]
        if statement.type != "expression_statement" or not statement.named_children:
            return None
        value = statement.named_children[0]
        if value.type not in {"string", "concatenated_string"}:
            return None
        return node_text(value, source).strip("\"'")

    def symbol_metadata(
        self,
        node: Node,
        source: bytes,
        kind: SymbolKind,
        name: str,
    ) -> dict[str, Any]:
        metadata = super().symbol_metadata(node, source, kind, name)
        parent = node.parent
        if parent is not None and parent.type == "decorated_definition":
            decorators = [
                node_text(child, source)
                for child in parent.named_children
                if child.type == "decorator"
            ]
            if any(_looks_like_route(value) for value in decorators):
                metadata["is_route"] = True
        return metadata

    def fact_kind(self, node: Node, source: bytes) -> FactKind | None:
        if node.type == "argument_list":
            parent = node.parent
            if parent is None or parent.type != "class_definition":
                return None
        if node.type == "decorator" and _looks_like_route(node_text(node, source)):
            return FactKind.ROUTE
        return super().fact_kind(node, source)


class JavaScriptAdapter(TreeSitterAdapter):
    language = Language.JAVASCRIPT
    parser_name = "javascript"
    import_node_types = frozenset({"import_statement"})
    export_node_types = frozenset({"export_statement"})
    call_node_types = frozenset({"call_expression"})
    inheritance_node_types = frozenset({"class_heritage", "extends_clause", "implements_clause"})

    def classify_symbol(
        self, node: Node, source: bytes, parent: ParentSymbol | None
    ) -> SymbolKind | None:
        if node.type in {"class_declaration", "class"}:
            return SymbolKind.CLASS
        if node.type in {
            "function_declaration",
            "generator_function_declaration",
        }:
            return SymbolKind.METHOD if self.is_method(parent) else SymbolKind.FUNCTION
        if node.type in {"method_definition", "method_signature"}:
            name = node.child_by_field_name("name")
            if name is not None and node_text(name, source) == "constructor":
                return SymbolKind.CONSTRUCTOR
            return SymbolKind.METHOD
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value is not None and value.type in {
                "arrow_function",
                "function_expression",
                "generator_function",
            }:
                return SymbolKind.FUNCTION
            declaration = node.parent
            if declaration is not None and node_text(declaration, source).lstrip().startswith(
                "const "
            ):
                return SymbolKind.CONSTANT
        return None

    def parameters_node(self, node: Node) -> Node | None:
        parameters = super().parameters_node(node)
        if parameters is not None or node.type != "variable_declarator":
            return parameters
        value = node.child_by_field_name("value")
        return value.child_by_field_name("parameters") if value is not None else None

    def return_type_node(self, node: Node) -> Node | None:
        return_type = node.child_by_field_name("return_type")
        if return_type is not None or node.type != "variable_declarator":
            return return_type
        value = node.child_by_field_name("value")
        return value.child_by_field_name("return_type") if value is not None else None

    def signature(self, node: Node, source: bytes) -> str:
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            body = value.child_by_field_name("body") if value is not None else None
            end_byte = body.start_byte if body is not None else node.end_byte
            return " ".join(node_text(node, source, end_byte=end_byte).split())
        return super().signature(node, source)

    def symbol_metadata(
        self,
        node: Node,
        source: bytes,
        kind: SymbolKind,
        name: str,
    ) -> dict[str, Any]:
        metadata = super().symbol_metadata(node, source, kind, name)
        parent = node.parent
        if parent is not None and parent.type == "export_statement":
            metadata["exported"] = True
        return metadata

    def fact_kind(self, node: Node, source: bytes) -> FactKind | None:
        if node.type == "implements_clause":
            return FactKind.IMPLEMENTS
        if node.type == "call_expression":
            function = node.child_by_field_name("function")
            target = node_text(function, source) if function is not None else ""
            if target in {"test", "it", "describe"}:
                return FactKind.TESTS
            if _looks_like_route(target):
                return FactKind.ROUTE
        return super().fact_kind(node, source)


class TypeScriptAdapter(JavaScriptAdapter):
    language = Language.TYPESCRIPT
    parser_name = "typescript"

    def classify_symbol(
        self, node: Node, source: bytes, parent: ParentSymbol | None
    ) -> SymbolKind | None:
        if node.type == "interface_declaration":
            return SymbolKind.INTERFACE
        if node.type == "type_alias_declaration":
            return SymbolKind.TYPE_ALIAS
        if node.type == "enum_declaration":
            return SymbolKind.ENUM
        return super().classify_symbol(node, source, parent)


class TsxAdapter(TypeScriptAdapter):
    language = Language.TSX
    parser_name = "tsx"


class DartAdapter(TreeSitterAdapter):
    language = Language.DART
    parser_name = "dart"
    import_node_types = frozenset({"import_or_export"})
    export_node_types = frozenset({"export_specification"})
    call_node_types = frozenset({"selector"})
    inheritance_node_types = frozenset(
        {"superclass", "interfaces", "mixins", "extension_type_implements"}
    )
    decorator_node_types = frozenset({"metadata"})

    def classify_symbol(
        self, node: Node, source: bytes, parent: ParentSymbol | None
    ) -> SymbolKind | None:
        if node.type == "class_definition":
            return SymbolKind.CLASS
        if node.type == "mixin_declaration":
            return SymbolKind.MIXIN
        if node.type == "extension_declaration":
            return SymbolKind.EXTENSION
        if node.type == "enum_declaration":
            return SymbolKind.ENUM
        if node.type == "function_signature":
            if parent is not None and parent.kind in {
                SymbolKind.METHOD,
                SymbolKind.CONSTRUCTOR,
            }:
                return None
            return SymbolKind.METHOD if self.is_method(parent) else SymbolKind.FUNCTION
        if node.type == "method_signature":
            nested = first_named_descendant(node, {"function_signature"})
            if nested is not None:
                return SymbolKind.METHOD
        if node.type in {"constructor_signature", "factory_constructor_signature"}:
            return SymbolKind.CONSTRUCTOR
        if node.type == "static_final_declaration":
            return SymbolKind.CONSTANT
        return None

    def symbol_source_range(self, node: Node) -> SourceRange:
        if node.type in {
            "method_signature",
            "constructor_signature",
            "factory_constructor_signature",
        }:
            body = node.next_named_sibling
            if body is not None and body.type == "function_body":
                start = node.start_point
                end = body.end_point
                return SourceRange(
                    start_byte=node.start_byte,
                    end_byte=body.end_byte,
                    start_line=start.row + 1,
                    end_line=end.row + 1,
                    start_column=start.column,
                    end_column=end.column,
                )
        return super().symbol_source_range(node)

    def associated_body_node(self, node: Node) -> Node | None:
        if node.type in {
            "method_signature",
            "constructor_signature",
            "factory_constructor_signature",
        }:
            body = node.next_named_sibling
            if body is not None and body.type == "function_body":
                return body
        return None

    def symbol_name_node(self, node: Node, source: bytes) -> Node | None:
        name = node.child_by_field_name("name")
        if name is not None:
            return name
        nested = first_named_descendant(
            node,
            {
                "function_signature",
                "constructor_signature",
                "factory_constructor_signature",
            },
        )
        if nested is not None:
            return nested.child_by_field_name("name")
        if node.type == "static_final_declaration":
            return next(
                (child for child in node.named_children if child.type == "identifier"),
                None,
            )
        return None

    def return_type_node(self, node: Node) -> Node | None:
        signature = (
            first_named_descendant(node, {"function_signature"})
            if node.type == "method_signature"
            else node
        )
        if signature is None:
            return None
        name = signature.child_by_field_name("name")
        for child in signature.named_children:
            if (
                name is not None
                and child.end_byte <= name.start_byte
                and (child.type.endswith("type") or "identifier" in child.type)
            ):
                return child
        return None

    def fact_kind(self, node: Node, source: bytes) -> FactKind | None:
        if node.type in {"interfaces", "extension_type_implements"}:
            return FactKind.IMPLEMENTS
        if node.type == "metadata" and _looks_like_route(node_text(node, source)):
            return FactKind.ROUTE
        return super().fact_kind(node, source)


def _looks_like_route(value: str) -> bool:
    lowered = value.lower().strip()
    return any(
        marker in lowered for marker in (".get", ".post", ".put", ".patch", ".delete", ".route")
    ) or lowered.lstrip("@").startswith(("get(", "post(", "put(", "patch(", "delete(", "route("))

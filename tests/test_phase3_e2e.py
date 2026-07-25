from pathlib import Path

import pytest

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.graph.contracts import GraphDirection, RelationKind
from monas_lens.graph.service import GraphService
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.search.service import SearchService


def _write_mixed_language_repository(root: Path) -> None:
    root.mkdir()
    (root / "python_base.py").write_text(
        "class PythonBase:\n    pass\n\nAPI_URL = 'https://example.invalid'\n",
        encoding="utf-8",
    )
    (root / "python_service.py").write_text(
        "import os\n"
        "from python_base import PythonBase\n\n"
        "class PythonService(PythonBase):\n"
        "    def helper(self) -> str:\n"
        "        return 'ok'\n\n"
        "    def python_handler(self) -> str:\n"
        "        return self.helper() + os.getenv('API_URL', '')\n",
        encoding="utf-8",
    )
    (root / "javascript_service.js").write_text(
        "export function javascript_handler() { return true; }\n",
        encoding="utf-8",
    )
    (root / "javascript_service.test.js").write_text(
        "import { javascript_handler } from './javascript_service.js';\n"
        "test('runs javascript handler', () => javascript_handler());\n",
        encoding="utf-8",
    )
    (root / "typescript_base.ts").write_text(
        "export class TypeScriptBase {}\nexport interface Contract {}\n",
        encoding="utf-8",
    )
    (root / "typescript_service.ts").write_text(
        "import { TypeScriptBase, Contract } from './typescript_base';\n"
        "export class TypeScriptService extends TypeScriptBase implements Contract {\n"
        "  typescript_handler(): string { return 'ok'; }\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "component.tsx").write_text(
        "export function tsx_handler() { return <section>ready</section>; }\n",
        encoding="utf-8",
    )
    (root / "service.dart").write_text(
        "class DartBase {}\n"
        "class DartService extends DartBase {\n"
        "  String helper() => 'ok';\n"
        "  String dartHandler() => helper();\n"
        "}\n",
        encoding="utf-8",
    )


def test_mixed_language_search_and_graph_end_to_end(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    _write_mixed_language_repository(repository_root)
    repository = RepositoryService(database, settings).add(repository_root)
    indexing = IndexService(database, settings)

    first = indexing.build(repository.id)
    noop = indexing.build(repository.id)
    status = indexing.status(repository.id)
    search = SearchService(database, settings)
    graph = GraphService(database, settings)

    expected_symbols = {
        "python_handler": "python_service.py",
        "javascript_handler": "javascript_service.js",
        "typescript_handler": "typescript_service.ts",
        "tsx_handler": "component.tsx",
        "dartHandler": "service.dart",
    }
    for symbol, relative_path in expected_symbols.items():
        response = search.search(symbol, repository.id)
        assert response.results[0].match_type == "exact"
        assert response.results[0].relative_path == relative_path

    call_graph = graph.neighbors(
        "PythonService.python_handler",
        repository.id,
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )
    relation_kinds = {
        edge.kind
        for edge in graph.traverse(
            "PythonService",
            repository.id,
            direction=GraphDirection.BOTH,
            depth=3,
        ).edges
    }

    assert first.parsed_files == 8
    assert first.relationships > 0
    assert noop.parsed_files == 0
    assert noop.graph_refreshed_facts == 0
    assert status.relationships == first.relationships
    assert not status.graph_dirty
    assert {node.name for node in call_graph.nodes} == {
        "helper",
        "python_handler",
    }
    assert RelationKind.INHERITS in relation_kinds

    all_relation_kinds = {
        kind
        for target in (
            "PythonService.python_handler",
            "javascript_handler",
            "TypeScriptService",
        )
        for kind in {
            edge.kind
            for edge in graph.traverse(
                target,
                repository.id,
                direction=GraphDirection.BOTH,
                depth=3,
            ).edges
        }
    }
    assert {
        RelationKind.CALLS,
        RelationKind.INHERITS,
        RelationKind.IMPLEMENTS,
        RelationKind.TESTED_BY,
        RelationKind.CONFIGURED_BY,
    } <= all_relation_kinds


def test_incremental_rename_failure_recovery_and_delete(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    source = repository_root / "service.py"
    source.write_text(
        "def helper() -> str:\n"
        "    return 'legacy_token'\n\n"
        "def run() -> str:\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(repository_root)
    indexing = IndexService(database, settings)
    search = SearchService(database, settings)
    graph = GraphService(database, settings)

    indexing.build(repository.id)
    initial_graph = graph.neighbors(
        "run",
        repository.id,
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )

    renamed_source = source.rename(repository_root / "renamed.py")
    renamed = indexing.build(repository.id)
    renamed_graph = graph.neighbors(
        "run",
        repository.id,
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )

    assert renamed.parsed_files == 1
    assert renamed.deleted_files == 1
    assert {result.relative_path for result in search.search("legacy_token").results} == {
        "renamed.py"
    }
    assert renamed_graph.root.relative_path == "renamed.py"

    renamed_source.write_bytes(b"def run():\n    return \xff\n")
    failed = indexing.build(repository.id)
    failed_graph = graph.neighbors(
        "run",
        repository.id,
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )

    assert failed.failed_files == 1
    assert failed.graph_refreshed_facts == 0
    assert search.search("legacy_token", repository.id).total > 0
    assert failed_graph.edges == renamed_graph.edges

    renamed_source.write_text(
        "def replacement() -> str:\n"
        "    return 'replacement_token'\n\n"
        "def run() -> str:\n"
        "    return replacement()\n",
        encoding="utf-8",
    )
    recovered = indexing.build(repository.id)
    recovered_graph = graph.neighbors(
        "run",
        repository.id,
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )

    assert recovered.parsed_files == 1
    assert recovered.stale_files == 0
    assert search.search("legacy_token", repository.id).total == 0
    assert search.search("replacement_token", repository.id).total > 0
    assert {node.name for node in recovered_graph.nodes} == {"replacement", "run"}
    assert recovered_graph.edges != initial_graph.edges

    renamed_source.unlink()
    deleted = indexing.build(repository.id)

    assert deleted.deleted_files == 1
    assert search.search("replacement_token", repository.id).total == 0
    with pytest.raises(MonasLensError) as missing:
        graph.neighbors("run", repository.id)
    assert missing.value.code == ErrorCode.GRAPH_QUERY_INVALID


def test_graph_queries_are_repository_scoped(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repositories = RepositoryService(database, settings)
    repository_ids: list[str] = []
    for name, target in (("first", "first_helper"), ("second", "second_helper")):
        root = tmp_path / name
        root.mkdir()
        (root / "service.py").write_text(
            f"def {target}() -> None:\n    pass\n\ndef caller() -> None:\n    {target}()\n",
            encoding="utf-8",
        )
        repository = repositories.add(root)
        IndexService(database, settings).build(repository.id)
        repository_ids.append(repository.id)

    graph = GraphService(database, settings)
    first = graph.neighbors(
        "caller",
        repository_ids[0],
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )
    second = graph.neighbors(
        "caller",
        repository_ids[1],
        direction=GraphDirection.OUTGOING,
        relation_kinds=frozenset({RelationKind.CALLS}),
    )

    assert first.repository_id == repository_ids[0]
    assert second.repository_id == repository_ids[1]
    assert {node.name for node in first.nodes} == {"caller", "first_helper"}
    assert {node.name for node in second.nodes} == {"caller", "second_helper"}

from pathlib import Path

from sqlalchemy import select

from monas_lens.config import Settings
from monas_lens.db.models import (
    FileModel,
    RelationshipModel,
    ResolutionDiagnosticModel,
    SymbolModel,
)
from monas_lens.db.session import Database
from monas_lens.graph.contracts import DiagnosticReason, RelationKind
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService


def _write_graph_fixture(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "base.py").write_text(
        "class Base:\n    pass\n\nclass Contract:\n    pass\n",
        encoding="utf-8",
    )
    (root / "pkg" / "service.py").write_text(
        "from .base import Base\n\n"
        "class Service(Base):\n"
        "    def helper(self) -> str:\n"
        "        return 'ok'\n\n"
        "    def run(self) -> str:\n"
        "        return self.helper()\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_service.py").write_text(
        "from pkg.service import Service\n\n"
        "def test_service() -> None:\n"
        "    assert Service().run() == 'ok'\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "base.ts").write_text(
        "export class TsBase {}\nexport interface Contract {}\n",
        encoding="utf-8",
    )
    (root / "src" / "service.ts").write_text(
        "import { TsBase, Contract } from './base';\n"
        "export class TsService extends TsBase implements Contract {}\n",
        encoding="utf-8",
    )


def _relationship_names(
    database: Database,
    repository_id: str,
) -> set[tuple[str, str | None, str | None]]:
    with database.session() as session:
        relationships = session.scalars(
            select(RelationshipModel).where(RelationshipModel.repository_id == repository_id)
        ).all()
        symbols = {symbol.id: symbol.name for symbol in session.scalars(select(SymbolModel)).all()}
    return {
        (
            relationship.kind,
            symbols.get(relationship.source_symbol_id),
            symbols.get(relationship.target_symbol_id),
        )
        for relationship in relationships
    }


def test_graph_builds_import_call_type_and_test_relationships(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _write_graph_fixture(repository_root)
    repository = RepositoryService(database, settings).add(repository_root)

    summary = IndexService(database, settings).build(repository.id)
    status = IndexService(database, settings).status(repository.id)
    relationships = _relationship_names(database, repository.id)

    assert summary.graph_refreshed_facts > 0
    assert summary.relationships > 0
    assert not status.graph_dirty
    assert {
        RelationKind.IMPORTS.value,
        RelationKind.CALLS.value,
        RelationKind.INHERITS.value,
        RelationKind.IMPLEMENTS.value,
        RelationKind.TESTED_BY.value,
    } <= {relationship[0] for relationship in relationships}
    assert (RelationKind.CALLS.value, "run", "helper") in relationships
    assert (RelationKind.INHERITS.value, "Service", "Base") in relationships
    assert (RelationKind.IMPLEMENTS.value, "TsService", "Contract") in relationships
    assert (RelationKind.TESTED_BY.value, "run", "test_service") in relationships


def test_graph_noop_and_target_change_refresh_are_incremental(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    _write_graph_fixture(repository_root)
    repository = RepositoryService(database, settings).add(repository_root)
    service = IndexService(database, settings)

    first = service.build(repository.id)
    with database.session() as session:
        first_ids = set(
            session.scalars(
                select(RelationshipModel.id).where(RelationshipModel.repository_id == repository.id)
            ).all()
        )
    noop = service.build(repository.id)

    assert first.graph_refreshed_facts > 0
    assert noop.parsed_files == 0
    assert noop.graph_refreshed_facts == 0

    (repository_root / "pkg" / "base.py").write_text(
        "class RenamedBase:\n    pass\n\nclass Contract:\n    pass\n",
        encoding="utf-8",
    )
    changed = service.build(repository.id)
    with database.session() as session:
        current_ids = set(
            session.scalars(
                select(RelationshipModel.id).where(RelationshipModel.repository_id == repository.id)
            ).all()
        )
        unresolved = session.scalars(
            select(ResolutionDiagnosticModel).where(
                ResolutionDiagnosticModel.repository_id == repository.id,
                ResolutionDiagnosticModel.reason == DiagnosticReason.UNRESOLVED.value,
                ResolutionDiagnosticModel.normalized_target == "Base",
            )
        ).all()

    assert changed.parsed_files == 1
    assert changed.graph_refreshed_facts > 1
    assert current_ids != first_ids
    assert unresolved


def test_ambiguous_repository_symbol_creates_diagnostic_without_edge(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "first.py").write_text(
        "def shared() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (repository_root / "second.py").write_text(
        "def shared() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (repository_root / "caller.py").write_text(
        "def caller() -> None:\n    shared()\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(repository_root)

    IndexService(database, settings).build(repository.id)

    with database.session() as session:
        caller_file = session.scalar(
            select(FileModel).where(FileModel.relative_path == "caller.py")
        )
        assert caller_file is not None
        ambiguous = session.scalars(
            select(ResolutionDiagnosticModel).where(
                ResolutionDiagnosticModel.file_id == caller_file.id,
                ResolutionDiagnosticModel.reason == DiagnosticReason.AMBIGUOUS.value,
            )
        ).all()
        call_edges = session.scalars(
            select(RelationshipModel).where(
                RelationshipModel.source_file_id == caller_file.id,
                RelationshipModel.kind == RelationKind.CALLS.value,
            )
        ).all()

    assert ambiguous
    assert not call_edges


def test_configuration_and_javascript_test_links_are_conservative(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "settings.py").write_text(
        "API_URL = 'https://example.invalid'\n",
        encoding="utf-8",
    )
    (repository_root / "service.py").write_text(
        "import os\n\ndef load_url() -> str:\n    return os.getenv('API_URL', '')\n",
        encoding="utf-8",
    )
    (repository_root / "service.js").write_text(
        "export function execute() { return true; }\n",
        encoding="utf-8",
    )
    (repository_root / "service.test.js").write_text(
        "import { execute } from './service.js';\ntest('executes service', () => execute());\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(repository_root)

    IndexService(database, settings).build(repository.id)
    relationships = _relationship_names(database, repository.id)

    assert (RelationKind.CONFIGURED_BY.value, "load_url", "API_URL") in relationships
    assert (
        RelationKind.TESTED_BY.value,
        "execute",
        "executes service",
    ) in relationships


def test_graph_closes_typed_receivers_reexports_implementations_and_schemas(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text(
        "class Service:\n    def run(self) -> str:\n        return 'ok'\n",
        encoding="utf-8",
    )
    (repository_root / "controller.py").write_text(
        "from service import Service\n\n"
        "def execute() -> str:\n"
        "    service = Service()\n"
        "    return service.run()\n",
        encoding="utf-8",
    )
    (repository_root / "base.py").write_text(
        "class Base:\n    def run(self, value: int) -> int:\n        return value\n",
        encoding="utf-8",
    )
    (repository_root / "child.py").write_text(
        "from base import Base\n\n"
        "class Child(Base):\n"
        "    def run(self, value: int) -> int:\n"
        "        return value + 1\n",
        encoding="utf-8",
    )
    (repository_root / "contracts.ts").write_text(
        "export interface Runner { run(value: number): string; }\n",
        encoding="utf-8",
    )
    (repository_root / "runner.ts").write_text(
        "import { Runner } from './contracts';\n"
        "export class LocalRunner implements Runner {\n"
        "  run(value: number): string { return String(value); }\n"
        "}\n",
        encoding="utf-8",
    )
    (repository_root / "api.ts").write_text(
        "export function fetchUser(): string { return 'user'; }\n",
        encoding="utf-8",
    )
    (repository_root / "index.ts").write_text(
        "export { fetchUser } from './api';\n",
        encoding="utf-8",
    )
    (repository_root / "consumer.ts").write_text(
        "import { fetchUser } from './index';\n"
        "export function useUser(): string { return fetchUser(); }\n",
        encoding="utf-8",
    )
    (repository_root / "schemas.py").write_text(
        "class UserCreate:\n    def __init__(self, name: str) -> None:\n        self.name = name\n",
        encoding="utf-8",
    )
    (repository_root / "routes.py").write_text(
        "from schemas import UserCreate\n\n"
        "@app.post('/users')\n"
        "def create_user(payload: UserCreate) -> str:\n"
        "    return payload.name\n",
        encoding="utf-8",
    )
    (repository_root / "configuration.py").write_text(
        "import os\n\ndef load_config() -> str:\n    return os.getenv('API_URL', '')\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(repository_root)

    IndexService(database, settings).build(repository.id)
    relationships = _relationship_names(database, repository.id)

    assert (RelationKind.CALLS.value, "execute", "run") in relationships
    assert (RelationKind.IMPLEMENTS.value, "LocalRunner", "Runner") in relationships
    assert (RelationKind.OVERRIDES.value, "run", "run") in relationships
    assert (RelationKind.CALLS.value, "useUser", "fetchUser") in relationships
    assert (RelationKind.USES_SCHEMA.value, "create_user", "UserCreate") in relationships
    assert (
        RelationKind.CONFIGURED_BY.value,
        "load_config",
        "load_config",
    ) in relationships

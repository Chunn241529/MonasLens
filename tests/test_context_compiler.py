from __future__ import annotations

import json
from pathlib import Path

from monas_lens.db.session import Database
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.compiler import ContextCompiler


def test_context_compiler_resolves_indexed_repository_deterministically(
    tmp_path: Path,
    database: Database,
    settings,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "service.py").write_text(
        "def helper() -> str:\n    return 'ok'\n\ndef run_service() -> str:\n    return helper()\n",
        encoding="utf-8",
    )
    repository = RepositoryService(database, settings).add(repository_root)
    IndexService(database, settings).build(repository.id)
    compiler = ContextCompiler(database, settings)
    request = {
        "task": "Explain run_service",
        "repository": repository.id,
        "include_git_diff": False,
        "max_tokens": 2_000,
    }

    first = compiler.resolve(request)
    second = compiler.resolve(request)

    assert first.repository_id == repository.id
    assert first.primary_targets[0].candidate.qualified_name == "run_service"
    assert first.snippets
    assert first.budget.requested_tokens == 2_000
    assert json.dumps(first.model_dump(mode="json"), sort_keys=True) == json.dumps(
        second.model_dump(mode="json"), sort_keys=True
    )

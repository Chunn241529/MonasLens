from __future__ import annotations

import json
from pathlib import Path

from monas_lens.config import Settings
from monas_lens.db.session import Database
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.compiler import ContextCompiler


def test_seven_mixed_language_context_scenarios_are_focused_and_deterministic(
    tmp_path: Path,
    database: Database,
    settings: Settings,
) -> None:
    repository_root = tmp_path / "mixed-repository"
    repository_root.mkdir()
    _write_mixed_language_fixture(repository_root)
    repository = RepositoryService(database, settings).add(repository_root)
    IndexService(database, settings).build(repository.id)
    compiler = ContextCompiler(database, settings)
    scenarios = (
        ("Fix the missing import used by load_user", "python_service.py"),
        ("Fix the wrong configuration key in ApiConfig", "configuration.ts"),
        ("Fix the broken API schema UserResponse", "schema.ts"),
        ("Fix expired session logic in SessionService.isExpired", "session.ts"),
        ("Rename LegacyFormatter across files", "formatter.dart"),
        ("Add a missing regression test for calculateTotal", "billing.js"),
        ("Explain the unrelated change near untouched_helper", "unrelated.py"),
    )

    for task, expected_path in scenarios:
        request = {
            "task": task,
            "repository": repository.id,
            "max_tokens": 3_000,
            "include_git_diff": False,
        }
        first = compiler.resolve(request)
        second = compiler.resolve(request)

        assert first.primary_targets
        assert first.primary_targets[0].candidate.relative_path == expected_path
        assert any(snippet.relative_path == expected_path for snippet in first.snippets)
        assert first.budget.used_tokens <= first.budget.requested_tokens
        assert first.confidence.expansion_count <= 1
        assert json.dumps(first.model_dump(mode="json"), sort_keys=True) == json.dumps(
            second.model_dump(mode="json"), sort_keys=True
        )


def _write_mixed_language_fixture(root: Path) -> None:
    (root / "python_service.py").write_text(
        "def load_user(user_id: str) -> dict[str, str]:\n    return {'id': user_id}\n",
        encoding="utf-8",
    )
    (root / "configuration.ts").write_text(
        "export class ApiConfig {\n  apiKey: string = 'local';\n}\n",
        encoding="utf-8",
    )
    (root / "schema.ts").write_text(
        "export interface UserResponse {\n  id: string;\n}\n",
        encoding="utf-8",
    )
    (root / "session.ts").write_text(
        "export class SessionService {\n"
        "  isExpired(expiresAt: number): boolean {\n"
        "    return expiresAt < Date.now();\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "formatter.dart").write_text(
        "class LegacyFormatter {\n  String format(String value) => value.trim();\n}\n",
        encoding="utf-8",
    )
    (root / "billing.js").write_text(
        "export function calculateTotal(values) {\n"
        "  return values.reduce((total, value) => total + value, 0);\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "unrelated.py").write_text(
        "def untouched_helper() -> str:\n    return 'stable'\n",
        encoding="utf-8",
    )

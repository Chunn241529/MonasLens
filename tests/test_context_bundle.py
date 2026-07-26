from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from sqlalchemy import select

from monas_lens.config import Settings
from monas_lens.db.models import FileModel, SymbolModel
from monas_lens.db.session import Database
from monas_lens.errors import ErrorCode, MonasLensError
from monas_lens.indexing.service import IndexService
from monas_lens.repositories import RepositoryService
from monas_lens.retrieval.bundle import ContextBundleBuilder
from monas_lens.retrieval.contracts import (
    CandidateRole,
    ConfidenceComponents,
    ConfidenceResult,
    ConfidenceStatus,
    ContextSnippet,
    ContextSourceReference,
    EntityType,
    EvidenceKind,
    RankedCandidate,
    RetrievalCandidate,
    RetrievalDiagnosticCode,
    RetrievalEvidence,
    ScoreComponents,
    TaskAction,
    TaskResolution,
    TokenEstimate,
)
from monas_lens.retrieval.retriever import (
    GitDiffHunk,
    IndexedChunk,
    SubprocessGitDiffAdapter,
)
from monas_lens.retrieval.validation import suggest_validation_commands


class _ChunkLookup:
    def __init__(self, chunks: Sequence[IndexedChunk]) -> None:
        self._chunks = {chunk.candidate_identity: chunk for chunk in chunks}

    def lookup(
        self,
        repository_id: str,
        candidates: Sequence[RetrievalCandidate],
    ) -> tuple[IndexedChunk, ...]:
        assert all(candidate.repository_id == repository_id for candidate in candidates)
        return tuple(
            self._chunks[candidate.identity]
            for candidate in reversed(candidates)
            if candidate.identity in self._chunks
        )


def test_bundle_uses_the_narrowest_indexed_chunk(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root, repository_id = _register_repository(database, settings, tmp_path)
    (repository_root / "service.py").write_text(
        "def alpha() -> str:\n    return 'alpha'\n\ndef beta() -> str:\n    return 'beta'\n",
        encoding="utf-8",
    )
    IndexService(database, settings).build(repository_id)
    with database.session() as session:
        symbol = session.scalar(select(SymbolModel).where(SymbolModel.name == "alpha"))
        assert symbol is not None
        file = session.get(FileModel, symbol.file_id)
        assert file is not None
        candidate = RetrievalCandidate(
            repository_id=repository_id,
            entity_type=EntityType.SYMBOL,
            entity_id=symbol.id,
            relative_path=file.relative_path,
            language=symbol.language,
            kind=symbol.kind,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            role_hints=(CandidateRole.PRIMARY,),
            evidence=(
                RetrievalEvidence(
                    kind=EvidenceKind.EXACT,
                    query="alpha",
                    source_score=1,
                    explanation="Exact fixture match.",
                ),
            ),
            retrieval_ordinal=0,
        )
    ranked = RankedCandidate(
        candidate=candidate,
        components=ScoreComponents(exact=1),
        score=1,
        rank=1,
    )

    bundle = ContextBundleBuilder(database, settings).build(
        repository_id,
        TaskResolution(normalized_task="Explain alpha", action=TaskAction.EXPLAIN),
        (ranked,),
        _confidence(),
        requested_tokens=1_000,
    )

    assert len(bundle.snippets) == 1
    assert bundle.snippets[0].content.startswith("def alpha")
    assert "def beta" not in bundle.snippets[0].content


def test_bundle_materializes_deduplicates_and_selects_relevant_git_context(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    repository_root, repository_id = _register_repository(database, settings, tmp_path)
    (repository_root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (repository_root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    source = "def run() -> str:\n    return 'ok'\n"
    test_source = "def test_run() -> None:\n    assert run() == 'ok'\n"
    primary = _ranked(repository_id, "primary", "src/service.py", CandidateRole.PRIMARY, 1, 0.95)
    duplicate = _ranked(
        repository_id,
        "duplicate",
        "src/service_alias.py",
        CandidateRole.DEPENDENCY,
        2,
        0.80,
    )
    test = _ranked(
        repository_id,
        "test",
        "tests/test_service.py",
        CandidateRole.TEST,
        3,
        0.75,
    )
    lookup = _ChunkLookup(
        (
            _chunk(primary, source, start_line=10),
            _chunk(duplicate, source, start_line=20),
            _chunk(test, test_source, start_line=1, kind="test"),
        )
    )
    resolution = TaskResolution(
        normalized_task="Fix service run",
        action=TaskAction.CHANGE,
        path_candidates=("src/service.py",),
    )
    hunks = (
        _git_hunk("src/service.py", "@@ -10 +10 @@\n-old\n+new\n"),
        _git_hunk("docs/unrelated.md", "@@ -1 +1 @@\n-old\n+new\n"),
        _git_hunk("../outside.py", "@@ -1 +1 @@\n-old\n+new\n"),
    )
    builder = ContextBundleBuilder(database, settings, chunk_lookup=lookup)

    first = builder.build(
        repository_id,
        resolution,
        (duplicate, test, primary),
        _confidence(),
        requested_tokens=2_000,
        git_diff_hunks=hunks,
    )
    second = builder.build(
        repository_id,
        resolution,
        (primary, duplicate, test),
        _confidence(),
        requested_tokens=2_000,
        git_diff_hunks=tuple(reversed(hunks)),
    )

    assert first.model_dump_json() == second.model_dump_json()
    assert [snippet.role for snippet in first.snippets] == [
        CandidateRole.PRIMARY,
        CandidateRole.TEST,
        CandidateRole.GIT_DIFF,
    ]
    assert {reference.entity_id for reference in first.snippets[0].provenance} == {
        "primary",
        "duplicate",
    }
    assert [target.candidate.entity_id for target in first.primary_targets] == ["primary"]
    assert first.snippets[-1].relative_path == "src/service.py"
    assert first.validation_commands[0].arguments == (
        "uv",
        "run",
        "pytest",
        "tests/test_service.py",
    )
    assert {diagnostic.code.value for diagnostic in first.diagnostics} == {"git_unavailable"}
    assert "outside.py" not in first.model_dump_json()
    assert first.truncated


def test_bundle_crops_at_line_boundaries_around_the_ranked_range(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    _, repository_id = _register_repository(database, settings, tmp_path)
    bounded_settings = settings.model_copy(
        update={
            "context_token_safety_margin": 0,
            "context_response_envelope_tokens": 0,
        }
    )
    ranked = _ranked(
        repository_id,
        "large-primary",
        "src/large.py",
        CandidateRole.PRIMARY,
        1,
        1.0,
        start_line=50,
        end_line=50,
    )
    source = "\n".join(f"line_{line:03d} = '{'x' * 24}'" for line in range(1, 101))
    lookup = _ChunkLookup((_chunk(ranked, source, start_line=1),))

    bundle = ContextBundleBuilder(
        database,
        bounded_settings,
        chunk_lookup=lookup,
    ).build(
        repository_id,
        TaskResolution(normalized_task="Change large primary", action=TaskAction.CHANGE),
        (ranked,),
        _confidence(),
        requested_tokens=256,
    )

    snippet = bundle.snippets[0]
    assert snippet.cropped
    assert snippet.start_line <= 50 <= snippet.end_line
    assert "line_050" in snippet.content
    assert "omitted" in snippet.content
    assert snippet.content_hash == hashlib.sha256(snippet.content.encode()).hexdigest()
    assert bundle.budget.used_tokens + bundle.budget.reserved_tokens <= 256
    assert bundle.budget.pre_budget_tokens > bundle.budget.used_tokens
    assert bundle.budget.cropped
    assert bundle.truncated


def test_bundle_enforces_role_caps_and_reports_budget_omissions(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    _, repository_id = _register_repository(database, settings, tmp_path)
    bounded_settings = settings.model_copy(
        update={
            "context_max_primary_targets": 1,
            "context_token_safety_margin": 0,
            "context_response_envelope_tokens": 0,
        }
    )
    ranked = tuple(
        _ranked(
            repository_id,
            f"primary-{index}",
            f"src/service_{index}.py",
            CandidateRole.PRIMARY,
            index,
            1 - (index / 10),
        )
        for index in (1, 2)
    )
    lookup = _ChunkLookup(
        tuple(
            _chunk(item, f"def service_{index}():\n    pass\n") for index, item in enumerate(ranked)
        )
    )

    bundle = ContextBundleBuilder(
        database,
        bounded_settings,
        chunk_lookup=lookup,
    ).build(
        repository_id,
        TaskResolution(normalized_task="Change services", action=TaskAction.CHANGE),
        ranked,
        _confidence(),
        requested_tokens=1_000,
    )

    assert len(bundle.snippets) == 1
    assert len(bundle.primary_targets) == 1
    assert bundle.budget.omitted_items == 1
    assert RetrievalDiagnosticCode.BUDGET_OMITTED in {
        diagnostic.code for diagnostic in bundle.diagnostics
    }
    assert bundle.truncated


def test_bundle_rejects_foreign_candidates_and_invalid_budgets(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> None:
    _, repository_id = _register_repository(database, settings, tmp_path)
    foreign = _ranked(
        "foreign-repository",
        "foreign",
        "src/foreign.py",
        CandidateRole.PRIMARY,
        1,
        1,
    )
    builder = ContextBundleBuilder(database, settings, chunk_lookup=_ChunkLookup(()))

    with pytest.raises(MonasLensError) as foreign_error:
        builder.build(
            repository_id,
            TaskResolution(normalized_task="Fix foreign"),
            (foreign,),
            _confidence(),
            requested_tokens=1_000,
        )
    with pytest.raises(MonasLensError) as budget_error:
        builder.build(
            repository_id,
            TaskResolution(normalized_task="Fix budget"),
            (),
            _confidence(),
            requested_tokens=settings.context_max_total_tokens + 1,
        )

    assert foreign_error.value.code is ErrorCode.CONTEXT_RETRIEVAL_FAILED
    assert budget_error.value.code is ErrorCode.CONTEXT_BUDGET_INVALID


def test_validation_suggestions_are_manifest_driven_argument_arrays(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    (tmp_path / "pubspec.yaml").write_text("name: fixture\n", encoding="utf-8")
    snippets = (
        _context_snippet("tests/service.test.ts", "typescript"),
        _context_snippet("test/service_test.dart", "dart"),
    )

    commands = suggest_validation_commands(tmp_path, snippets)

    assert [command.arguments for command in commands] == [
        ("pnpm", "test", "--", "tests/service.test.ts"),
        ("dart", "test", "test/service_test.dart"),
    ]
    assert all(command.working_directory == "." for command in commands)
    assert suggest_validation_commands(tmp_path / "missing", snippets) == ()


def test_git_diff_adapter_reports_invalid_paths_and_bounds_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = b"--- a/inside.py\n+++ b/../../outside.py\n@@ -1 +1 @@\n-old\n+new\n" + (b"x" * 100)

    def fake_run(arguments: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(arguments, 0, stdout=output)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = SubprocessGitDiffAdapter(timeout_seconds=1, max_bytes=80).collect(
        tmp_path,
        max_hunks=5,
    )

    assert result.hunks == ()
    assert result.invalid_paths == 1
    assert result.truncated


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CompletedProcess(("git", "diff"), 1, stdout=b""),
        subprocess.TimeoutExpired(("git", "diff"), 1),
    ],
)
def test_git_diff_adapter_propagates_bounded_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: subprocess.CompletedProcess[bytes] | subprocess.TimeoutExpired,
) -> None:
    def fake_run(
        arguments: tuple[str, ...],
        **_: object,
    ) -> subprocess.CompletedProcess[bytes]:
        if isinstance(failure, subprocess.TimeoutExpired):
            raise failure
        return failure

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises((OSError, subprocess.TimeoutExpired)):
        SubprocessGitDiffAdapter(timeout_seconds=1, max_bytes=1_000).collect(
            tmp_path,
            max_hunks=1,
        )


def _register_repository(
    database: Database,
    settings: Settings,
    tmp_path: Path,
) -> tuple[Path, str]:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    repository_id = RepositoryService(database, settings).add(repository_root).id
    return repository_root, repository_id


def _ranked(
    repository_id: str,
    entity_id: str,
    relative_path: str,
    role: CandidateRole,
    rank: int,
    score: float,
    *,
    start_line: int = 1,
    end_line: int = 2,
) -> RankedCandidate:
    candidate = RetrievalCandidate(
        repository_id=repository_id,
        entity_type=EntityType.SYMBOL,
        entity_id=entity_id,
        relative_path=relative_path,
        language=_language_for_path(relative_path),
        kind="test" if role is CandidateRole.TEST else "function",
        name=entity_id,
        qualified_name=entity_id,
        start_line=start_line,
        end_line=end_line,
        role_hints=(role,),
        evidence=(
            RetrievalEvidence(
                kind=EvidenceKind.LEXICAL,
                query=entity_id,
                source_score=score,
                explanation="Fixture lexical evidence.",
            ),
        ),
        retrieval_ordinal=rank - 1,
    )
    return RankedCandidate(
        candidate=candidate,
        components=ScoreComponents(lexical=score),
        score=score,
        rank=rank,
    )


def _chunk(
    ranked: RankedCandidate,
    source: str,
    *,
    start_line: int = 1,
    kind: str = "function",
) -> IndexedChunk:
    line_count = max(len(source.splitlines()), 1)
    candidate = ranked.candidate
    return IndexedChunk(
        candidate_identity=candidate.identity,
        chunk_id=f"chunk-{candidate.entity_id}",
        file_id=f"file-{candidate.entity_id}",
        relative_path=candidate.relative_path,
        language=candidate.language,
        kind=kind,
        content_hash=hashlib.sha256(source.encode()).hexdigest(),
        source_text=source,
        start_line=start_line,
        end_line=start_line + line_count - 1,
    )


def _confidence() -> ConfidenceResult:
    components = ConfidenceComponents(
        primary_target_certainty=1,
        evidence_agreement=1,
        separation=1,
        role_coverage=1,
    )
    return ConfidenceResult(
        initial_confidence=1,
        final_confidence=1,
        status=ConfidenceStatus.ACCEPTED,
        initial_components=components,
        final_components=components,
    )


def _git_hunk(relative_path: str, content: str) -> GitDiffHunk:
    return GitDiffHunk(
        relative_path=relative_path,
        old_start_line=1,
        new_start_line=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
    )


def _context_snippet(relative_path: str, language: str) -> ContextSnippet:
    content = "test content"
    estimate = TokenEstimate(
        estimator_name="fixture",
        estimator_version="1",
        is_exact=False,
        characters=len(content),
        utf8_bytes=len(content.encode()),
        estimated_tokens=3,
    )
    return ContextSnippet(
        role=CandidateRole.TEST,
        relative_path=relative_path,
        language=language,
        kind="test",
        start_line=1,
        end_line=1,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        provenance=(
            ContextSourceReference(
                entity_type=EntityType.SYMBOL,
                entity_id=relative_path,
                relative_path=relative_path,
                start_line=1,
                end_line=1,
            ),
        ),
        rank_score=1,
        token_estimate=estimate,
    )


def _language_for_path(relative_path: str) -> str:
    if relative_path.endswith(".dart"):
        return "dart"
    if relative_path.endswith(".ts"):
        return "typescript"
    return "python"

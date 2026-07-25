"""Typed contracts shared by graph normalization, building, and queries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RelationKind(StrEnum):
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    TESTED_BY = "tested_by"
    CONFIGURED_BY = "configured_by"


class TargetKind(StrEnum):
    MODULE = "module"
    SYMBOL = "symbol"
    CONFIGURATION = "configuration"


class DiagnosticReason(StrEnum):
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    UNSUPPORTED = "unsupported"


class GraphDirection(StrEnum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class NormalizedTarget:
    kind: TargetKind
    value: str
    qualifier: str | None = None
    alias: str | None = None
    imported_name: str | None = None
    candidate_paths: tuple[str, ...] = ()

    @property
    def dependency_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        keys.update(f"path:{path.casefold()}" for path in self.candidate_paths)
        if self.kind in {TargetKind.SYMBOL, TargetKind.CONFIGURATION}:
            keys.add(f"symbol:{self.value.casefold()}")
        if self.qualifier is not None:
            keys.add(f"qualified:{self.qualifier.casefold()}.{self.value.casefold()}")
        return frozenset(keys)


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    relation_kind: RelationKind | None
    targets: tuple[NormalizedTarget, ...]
    supported: bool = True
    diagnostic: str | None = None

    @property
    def dependency_keys(self) -> frozenset[str]:
        return frozenset(key for target in self.targets for key in target.dependency_keys)

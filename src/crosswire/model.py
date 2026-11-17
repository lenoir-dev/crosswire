from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from .git import FileChange

ParamKind = Literal['posonly', 'pos', 'vararg', 'kwonly', 'varkw']
SymbolKind = Literal['function', 'class', 'method', 'variable']
Severity = Literal['error', 'warning']


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    kind: ParamKind
    has_default: bool


@dataclass(frozen=True, slots=True)
class Symbol:
    module: str
    qualname: str
    kind: SymbolKind
    path: str
    line: int
    params: tuple[Param, ...] | None
    shape: str


@dataclass(frozen=True, slots=True)
class CallShape:
    positional: int
    keywords: tuple[str, ...]
    has_star: bool
    has_starstar: bool


@dataclass(frozen=True, slots=True)
class Reference:
    path: str
    line: int
    module: str
    name: str
    call: CallShape | None


@dataclass(frozen=True, slots=True)
class ApiChange:
    kind: Literal['removed', 'signature_changed']
    module: str
    qualname: str
    old: Symbol
    new: Symbol | None
    rename_hint: str | None


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    severity: Severity
    message: str
    branch: str
    other_branch: str
    path: str
    line: int
    symbol: str | None
    hint: str | None = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Report:
    base_by_pair: dict[tuple[str, str], str]
    findings: list[Finding]
    coverage: str = 'complete'
    limitations: dict | None = None


@dataclass(frozen=True, slots=True)
class BranchSummary:
    """Changes introduced by one tip relative to its base."""

    label: str
    tip: str
    base: str
    roots: tuple[str, ...]
    changes: tuple[FileChange, ...]
    api: dict[str, tuple[ApiChange, ...]]
    references: tuple[Reference, ...]
    definitions: dict[str, dict[str, Symbol]]
    redefined: frozenset[tuple[str, str]]
    migrations: dict[str, str]
    touched_modules: frozenset[str]
    referenced_modules: frozenset[str]

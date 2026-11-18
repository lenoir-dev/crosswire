"""Versioned, parser-independent language contracts.

Opaque payloads belong to their adapter. None of these objects are public report
fields: the T21 compatibility facades retain the 0.4 serialization contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from .. import git

ADAPTER_API_VERSION = 1
Status = Literal['valid', 'broken', 'unknown']


class Reason(str, Enum):
    EXTERNAL = 'external'
    SKIPPED_BLOB = 'skipped-blob'
    PARSE_FAILURE = 'parse-failure'
    OPEN_NAMESPACE = 'open-namespace'
    UNSUPPORTED = 'unsupported-construct'
    DEPTH_LIMIT = 'depth-limit'
    CONSTRAINT_DEPENDENT = 'constraint-dependent'
    ABSENT = 'absent'
    INCOMPATIBLE_CALL = 'incompatible-call'
    INVALID_BASELINE = 'invalid-baseline'


@dataclass(frozen=True, slots=True, order=True)
class NamespaceId:
    language: str
    name: str


@dataclass(frozen=True, slots=True, order=True)
class SymbolId:
    namespace: NamespaceId
    name: str
    discriminator: str = ''


@dataclass(frozen=True, slots=True)
class Span:
    path: str
    line: int
    end_line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Gap:
    category: str
    span: Span
    detail: str


@dataclass(frozen=True, slots=True)
class Declaration:
    identity: SymbolId
    kind: str
    visibility: str
    span: Span
    signature: object | None
    guards: tuple[object, ...] = ()
    payload: object = None


@dataclass(frozen=True, slots=True)
class SymbolGroup:
    identity: SymbolId
    declarations: tuple[Declaration, ...]


@dataclass(frozen=True, slots=True)
class Use:
    target: SymbolId
    span: Span
    call: object | None = None
    caller: NamespaceId | None = None
    kind: str = 'member'

    @property
    def language(self):
        return self.target.namespace.language

    @property
    def module(self):
        return self.target.namespace.name

    @property
    def name(self):
        return self.target.name

    @property
    def path(self):
        return self.span.path

    @property
    def line(self):
        return self.span.line


@dataclass(frozen=True, slots=True)
class Verdict:
    status: Status
    reason: Reason | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Resolution:
    verdict: Status
    binding: SymbolGroup | None
    files: tuple[str, ...]
    reason: Reason | None = None
    detail: str | None = None
    dependencies: tuple[str, ...] = ()
    gaps: tuple[Gap, ...] = ()

    @property
    def status(self):
        return self.verdict


@dataclass(frozen=True, slots=True)
class Source:
    path: str
    text: str
    namespace: str | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Read-only access to one immutable tree and explicit analysis options."""

    repo: Path
    commit: str
    roots: tuple[str, ...] = ('.',)
    tracking: bool = True

    def read(self, path: str) -> str | None:
        return git.read_file(self.repo, self.commit, path)

    def list(self, prefix: str = '') -> tuple[str, ...]:
        return tuple(git.list_files(self.repo, self.commit, prefix))

    def entry(self, path: str):
        return git.tree_entries(str(self.repo), self.commit).get(path)

    def changes_from(self, base: str):
        return tuple(git.changed_files(self.repo, base, self.commit))

    def ancestors(self, commits):
        return git.ancestor_relations(self.repo, commits)


@dataclass(frozen=True, slots=True)
class ApiDelta:
    identity: SymbolId
    kind: str
    old: SymbolGroup
    new: SymbolGroup | None
    rename_hint: str | None = None


@dataclass(frozen=True, slots=True)
class LanguageSummary:
    language: str
    api: tuple[ApiDelta, ...]
    uses: tuple[Use, ...]
    definitions: dict[SymbolId, SymbolGroup]
    redefined: frozenset[SymbolId]
    touched_namespaces: frozenset[NamespaceId]
    referenced_namespaces: frozenset[NamespaceId]
    rule_data: object = None
    legacy: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class Scope:
    paths: tuple[str, ...]
    context: object


@dataclass(frozen=True, slots=True)
class Violation:
    identity: tuple[object, ...]
    rule: str
    severity: str
    span: Span
    message: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    phase: Literal['pairwise', 'state']


@runtime_checkable
class LanguageAdapter(Protocol):
    name: str
    version: str

    def claims(self, path: str) -> bool: ...
    def context(self, snap: Snapshot) -> object: ...
    def fingerprint(self, ctx: object) -> str: ...
    def namespaces_of(self, path: str, ctx: object) -> tuple[str, ...]: ...
    def normalize(self, name: str, kind: str) -> str: ...
    def symbols(self, src: Source, ctx: object) -> dict[SymbolId, SymbolGroup]: ...
    def uses(self, src: Source, ctx: object) -> tuple[Use, ...]: ...
    def resolve(self, snap: Snapshot, use: Use, ctx: object) -> Resolution: ...
    def resolve_namespace(self, snap: Snapshot, use: Use, ctx: object) -> Resolution: ...
    def summarize(self, base_snap: Snapshot, tip_snap: Snapshot, changes, ctx: object) -> LanguageSummary: ...
    def api_changes(self, old: dict[SymbolId, SymbolGroup], new: dict[SymbolId, SymbolGroup]) -> tuple[ApiDelta, ...]: ...
    def check_call(self, use: Use, old: SymbolGroup | None, new: SymbolGroup | None) -> Verdict: ...
    def gaps(self, src: Source, ctx: object) -> tuple[Gap, ...]: ...
    def duplicate_policy(self, kind: str) -> str: ...
    def member_resolvable(self, identity: SymbolId) -> bool: ...
    def definitions_equal(self, before: Snapshot, old: SymbolGroup, after: Snapshot, new: SymbolGroup, ctx: object) -> bool: ...
    def violations(self, snapshot: Snapshot, scope: Scope) -> list[Violation]: ...
    def rules(self) -> tuple[Rule, ...]: ...
    def pairwise_rules(self, pair) -> list: ...
    def state_rules(self, repo, target, state, labels, summaries, ancestors) -> list: ...
    def hint(self, finding) -> str | None: ...
    def state_hint(self, snapshot: Snapshot, finding) -> str | None: ...
    def call_hint(self, verdict: Verdict, bindings: SymbolGroup | None) -> str | None: ...
    def breakage(self, use: Use, old: Resolution, new: Resolution, snap: Snapshot, ctx: object) -> Verdict: ...
    def locate(self, snap: Snapshot, use: Use, ctx: object) -> tuple[int, str] | None: ...
    def signature_known(self, group: SymbolGroup | None) -> bool: ...
    def encode_summary(self, summary: LanguageSummary) -> dict: ...
    def decode_summary(self, data: dict) -> LanguageSummary: ...

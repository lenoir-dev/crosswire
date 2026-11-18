"""Python adapter: all syntax, binding, delta and language-rule policy."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, replace
from functools import lru_cache

from ... import git
from ...model import BranchSummary, Reference
from ...diffing import added_references
from ...parsing import PARSE_ERRORS
from ..base import (
    ADAPTER_API_VERSION, ApiDelta, Declaration, Gap, LanguageSummary,
    NamespaceId, Reason, Resolution, Rule, Snapshot, Source, Span,
    SymbolGroup, SymbolId, Use, Verdict,
)
from .analyzer import (
    module_name_for_path, extract_symbols, cached_references,
    definition_dumps, valid_syntax,
)
from .calls import binding_error, keyword_hint
from .coverage import _sites
from .diffing import api_changes
from . import migrations as cw004
from .hints import hint
from .state import StateIndex


@dataclass(frozen=True, slots=True)
class PythonContext:
    roots: tuple[str, ...]


class PythonAdapter:
    name = 'python'
    version = '1'

    def __init__(self, repo):
        self.repo = repo
        self.cache = {}
        self.module_cache = {}
        self.warned = set()
        self.parse_failures = 0
        self.indexes = {}

    def claims(self, path):
        return path.endswith('.py')

    def context(self, snap):
        return PythonContext(tuple(snap.roots))

    def source_roots(self, snap, configured=None):
        if configured is not None:
            return tuple(configured)
        return ('src', '.') if any(path.startswith('src/') for path in snap.list()) else ('.',)

    @staticmethod
    @lru_cache(maxsize=256)
    def fingerprint(ctx):
        data = json.dumps({'roots': ctx.roots}, separators=(',', ':'))
        return hashlib.sha256(data.encode()).hexdigest()

    def cache_identity(self, ctx):
        return (ADAPTER_API_VERSION, self.name, self.version, self.fingerprint(ctx))

    def namespaces_of(self, path, ctx):
        namespace = module_name_for_path(path, ctx.roots)
        return (namespace,) if namespace is not None else ()

    def normalize(self, name, kind):
        return name

    def identity(self, module, name):
        return SymbolId(NamespaceId(self.name, module), self.normalize(name, 'member'))

    def use(self, ref, ctx=None):
        if isinstance(ref, Use):
            return ref
        caller = self.namespaces_of(ref.path, ctx) if ctx is not None else ()
        return Use(self.identity(ref.module, ref.name), Span(ref.path, ref.line), ref.call,
                   NamespaceId(self.name, caller[0]) if caller else None)

    def group(self, symbol):
        if symbol is None:
            return None
        identity = self.identity(symbol.module, symbol.qualname)
        return SymbolGroup(identity, (Declaration(identity, symbol.kind, 'public',
            Span(symbol.path, symbol.line), symbol.params, payload=symbol),))

    def symbol(self, group):
        if group is None or len(group.declarations) != 1:
            return None
        return group.declarations[0].payload

    def symbols(self, src, ctx):
        module = src.namespace or next(iter(self.namespaces_of(src.path, ctx)), None)
        if module is None:
            return {}
        try:
            symbols = extract_symbols(src.text, module, src.path)
        except PARSE_ERRORS:
            return {}
        return {self.identity(module, name): self.group(symbol) for name, symbol in symbols.items()}

    def uses(self, src, ctx):
        module = src.namespace or next(iter(self.namespaces_of(src.path, ctx)), None)
        if module is None:
            return ()
        try:
            refs = cached_references(src.text, module, src.path,
                src.path.endswith('/__init__.py') or src.path == '__init__.py',
                cache_identity=self.cache_identity(ctx))
        except PARSE_ERRORS:
            return ()
        return tuple(self.use(ref, ctx) for ref in refs)

    def index(self, snap, ctx, consulted=None):
        key = (str(snap.repo), snap.commit, self.cache_identity(ctx), snap.tracking)
        # Untracked discovery must not leak into user-state coverage.
        if key not in self.indexes:
            self.indexes[key] = StateIndex(snap.repo, snap.commit, ctx.roots,
                self.module_cache, consulted, cache_identity=self.cache_identity(ctx))
        elif consulted is not None:
            self.indexes[key].consulted = consulted
        return self.indexes[key]

    def resolve(self, snap, use, ctx):
        use = self.use(use, ctx)
        if use.kind == 'namespace':
            return self.resolve_namespace(snap, use, ctx)
        return self._resolution(self.index(snap, ctx).resolve(use.module, use.name))

    def resolve_namespace(self, snap, use, ctx):
        use = self.use(use, ctx)
        index = self.index(snap, ctx)
        item = index._module(use.module)
        if item is None:
            return Resolution('unknown', None, (), Reason.EXTERNAL)
        path, source = item
        if source is None:
            return Resolution('unknown', None, (path,), Reason.SKIPPED_BLOB)
        if not valid_syntax(source):
            return Resolution('unknown', None, (path,), Reason.PARSE_FAILURE)
        return Resolution('valid', None, (path,))

    def _resolution(self, result):
        reason = {
            'stdlib': Reason.EXTERNAL, 'third-party': Reason.EXTERNAL,
            'skipped-blob': Reason.SKIPPED_BLOB, 'parse-failure': Reason.PARSE_FAILURE,
            'open-module': Reason.OPEN_NAMESPACE, 'unsupported-import': Reason.UNSUPPORTED,
            'cycle/depth': Reason.DEPTH_LIMIT,
        }.get(result.reason)
        return Resolution(result.status, self.group(result.symbol), result.files, reason,
                          result.reason)

    def check_call(self, use, old, new):
        call = use.call
        before, after = self.symbol(old), self.symbol(new)
        if (call is None or call.has_star or call.has_starstar or before is None
                or after is None or before.params is None or after.params is None):
            return Verdict('unknown', Reason.UNSUPPORTED, 'call signature unknown')
        if binding_error(call, before.params) is not None:
            return Verdict('unknown', Reason.INVALID_BASELINE, 'call already invalid')
        reason = binding_error(call, after.params)
        return (Verdict('broken', Reason.INCOMPATIBLE_CALL, reason) if reason else Verdict('valid'))

    def signature_known(self, group):
        symbol = self.symbol(group)
        return symbol is not None and symbol.params is not None

    def breakage(self, use, old, new, snap, ctx):
        """Python namespace deletion and call proof, shared by every trial."""
        if new.status == 'unknown' and old.files:
            if new.reason != Reason.EXTERNAL:
                return Verdict('unknown', new.reason, new.detail)
            for path in new.files:
                try:
                    source = snap.read(path)
                except git.SkippedBlob:
                    return Verdict('unknown', Reason.SKIPPED_BLOB)
                if source is not None and not valid_syntax(source):
                    return Verdict('unknown', Reason.PARSE_FAILURE)
            try:
                if any(snap.read(path) is None for path in old.files):
                    return Verdict('broken', Reason.ABSENT, 'undefined')
            except git.SkippedBlob:
                return Verdict('unknown', Reason.SKIPPED_BLOB)
        if new.status == 'broken':
            return Verdict('broken', Reason.ABSENT, 'undefined')
        if new.status != 'valid':
            return Verdict('unknown', new.reason, new.detail)
        return self.check_call(use, old.binding, new.binding)

    def locate(self, snap, use, ctx):
        try:
            source = snap.read(use.path)
        except git.SkippedBlob:
            return None
        if source is None:
            return use.line, 'branch'
        namespaces = self.namespaces_of(use.path, ctx)
        if not namespaces:
            return None
        try:
            found = cached_references(source, namespaces[0], use.path,
                use.path.endswith('/__init__.py') or use.path == '__init__.py',
                cache_identity=self.cache_identity(ctx))
        except PARSE_ERRORS:
            return None
        matching = [ref for ref in found
                    if (ref.module, ref.name, ref.call) == (use.module, use.name, use.call)]
        if not matching:
            return None
        chosen = min(matching, key=lambda ref: (abs(ref.line - use.line), ref.line))
        return chosen.line, 'integrated'

    def path_gaps(self, path, changed):
        if path.endswith('.pyi') and changed:
            return (Gap('unsupported', Span(path, 1), 'stub file'),)
        return ()

    def call_hint(self, verdict, bindings):
        symbol = self.symbol(bindings)
        if verdict.detail and symbol and symbol.params is not None:
            return keyword_hint(verdict.detail, symbol.params)
        return None

    def member_resolvable(self, identity):
        return '.' not in identity.name

    def duplicate_policy(self, kind):
        return 'different-definition-warning'

    def definitions_equal(self, before, old, after, new, ctx):
        left, right = self.symbol(old), self.symbol(new)
        a = self.parse(before.commit, left.path, left.module, ctx.roots)
        b = self.parse(after.commit, right.path, right.module, ctx.roots)
        return (a[2].get(left.qualname) if a is not None else None) == (b[2].get(right.qualname) if b is not None else None)

    def gaps(self, src, ctx):
        module = src.namespace or next(iter(self.namespaces_of(src.path, ctx)), None)
        sites, _ = _sites(src.text, module, src.path, self.cache_identity(ctx))
        return tuple(Gap(category, Span(src.path, line), detail) for category, line, detail in sites)

    def coverage_sites(self, src, ctx, extractor=None):
        # extractor keeps the legacy coverage._sites monkeypatch hook usable.
        key = ('coverage', hashlib.sha256(src.text.encode()).digest(), src.namespace,
               src.path, self.cache_identity(ctx))
        if key not in self.cache:
            self.cache[key] = (extractor(src.text, src.namespace, src.path)
                               if extractor is not None and extractor is not _sites else
                               _sites(src.text, src.namespace, src.path, self.cache_identity(ctx)))
        return self.cache[key]

    def coverage_reason(self, resolution):
        return resolution.detail or 'unsupported'

    def api_changes(self, old, new):
        old_symbols = {key.name: self.symbol(group) for key, group in old.items()}
        new_symbols = {key.name: self.symbol(group) for key, group in new.items()}
        return tuple(ApiDelta(self.identity(c.module, c.qualname), c.kind,
            self.group(c.old), self.group(c.new), c.rename_hint)
            for c in api_changes(old_symbols, new_symbols))

    def summarize(self, base_snap, tip_snap, changes, ctx):
        legacy = self._legacy_summary(base_snap, tip_snap, changes, ctx)
        return self.from_legacy(legacy)

    def from_legacy(self, legacy):
        return LanguageSummary(self.name,
            tuple(ApiDelta(self.identity(c.module, c.qualname), c.kind,
                self.group(c.old), self.group(c.new), c.rename_hint)
                for changes in legacy.api.values() for c in changes),
            tuple(self.use(ref, PythonContext(legacy.roots)) for ref in legacy.references),
            {self.identity(module, name): self.group(symbol)
                for module, symbols in legacy.definitions.items() for name, symbol in symbols.items()},
            frozenset(self.identity(module, name) for module, name in legacy.redefined),
            frozenset(NamespaceId(self.name, module) for module in legacy.touched_modules),
            frozenset(NamespaceId(self.name, module) for module in legacy.referenced_modules),
            legacy.migrations, legacy)

    def violations(self, snapshot, scope):
        # P2 explicitly preserves Python CW001/CW002/CW006 in 0.5a.
        # Python migration comparisons retain their phase hooks below.
        return []

    def rules(self):
        return (Rule('CW004', 'pairwise'), Rule('CW004', 'state'))

    def pairwise_rules(self, pair):
        return cw004.check(pair)

    def state_rules(self, repo, target, state, labels, summaries, ancestors):
        return cw004.state_findings(repo, target, state, labels, summaries, ancestors)

    def hint(self, finding):
        return hint(finding)

    def state_hint(self, snapshot, finding):
        return cw004.migration_hint(snapshot.repo, snapshot.commit, finding)

    def encode_summary(self, summary):
        from .codec import encode
        return encode(summary.legacy)

    def decode_summary(self, data):
        from .codec import decode
        return self.from_legacy(decode(data))

    def warn_parse(self, path, sha):
        """Warn once for a file in a revision, shared with coverage collection."""
        entry = Snapshot(self.repo, sha).entry(path)
        identity = (path, entry[1] if entry else sha)
        if identity not in self.warned:
            print(f'crosswire: warning: cannot parse {path}@{sha[:7]}', file=sys.stderr)
            self.warned.add(identity)

    def parse(self, sha, path, module, roots):
        """Parse."""
        try:
            source = Snapshot(self.repo, sha, tuple(roots)).read(path)
        except git.SkippedBlob:
            self.parse_failures += 1
            return None
        if source is None:
            return {}, [], {}
        key = (
            hashlib.sha256(
                source.encode()).digest(),
            module,
            path,
            self.cache_identity(ctx=self.context(Snapshot(self.repo, sha, tuple(roots)))))
        if key not in self.cache:
            try:
                self.cache[key] = (
                    extract_symbols(
                        source,
                        module,
                        path),
                    cached_references(
                        source,
                        module,
                        path,
                        path.endswith('/__init__.py') or path == '__init__.py',
                        cache_identity=self.cache_identity(self.context(Snapshot(self.repo, sha, tuple(roots))))),
                    definition_dumps(source))
            except PARSE_ERRORS:
                self.cache[key] = None
        value = self.cache[key]
        if value is None:
            self.parse_failures += 1
            self.warn_parse(path, sha)
            return None
        return value

    def references(self, sha, path, module, *, quiet=False, roots=('.',)):
        """Get cached references without extracting symbols or AST dumps."""
        try:
            source = Snapshot(self.repo, sha).read(path)
        except git.SkippedBlob:
            self.parse_failures += 1
            return None
        if source is None:
            return ()
        try:
            return cached_references(source, module, path,
                                     path.endswith('/__init__.py') or path == '__init__.py',
                                     cache_identity=self.cache_identity(self.context(Snapshot(self.repo, sha, tuple(roots)))))
        except PARSE_ERRORS:
            self.parse_failures += 1
            if not quiet:
                self.warn_parse(path, sha)
            return None

    def _legacy_summary(self, base_snap, tip_snap, changes, ctx):
        """Preserve Python 0.4 delta ordering and rename semantics."""
        base, sha, roots = base_snap.commit, tip_snap.commit, ctx.roots
        tip_index = self.index(tip_snap, ctx)
        api, refs, defs, dumps, modules, migrations, redefined = {}, [], {}, {}, {}, {}, set()
        for c in changes:
            oldpath = c.old_path if c.status == 'R' else c.path
            oldmod = module_name_for_path(oldpath, roots)
            newmod = module_name_for_path(c.path, roots)
            old_result = self.parse(
                base,
                oldpath,
                oldmod,
                roots) if oldmod and c.status != 'A' else (
                {},
                [],
                {})
            new_result = self.parse(
                sha,
                c.path,
                newmod,
                roots) if newmod and c.status != 'D' else (
                {},
                [],
                {})
            if old_result is None or new_result is None:
                continue
            oldsyms, oldrefs, olddumps = old_result
            newsyms, newrefs, newdumps = new_result
            renamed_refs = oldrefs
            if oldmod and (c.status in ('D', 'R') or oldmod != newmod):
                replacement = tip_index._module(oldmod)
                replacement_result = self.parse(sha, replacement[0], oldmod, roots) if replacement else ({}, [], {})
                if replacement_result is not None:
                    api.setdefault(oldmod, []).extend(api_changes(oldsyms, replacement_result[0]))
                oldsyms, oldrefs = {}, []
            if newmod:
                if c.status != 'D':
                    modules[newmod] = newsyms
                    redefined.update((newmod, name) for name in newsyms if name not in oldsyms or olddumps.get(
                        name) != newdumps.get(name))
                if c.status not in ('D', 'R'):
                    api.setdefault(
                        newmod, []).extend(
                        api_changes(
                            oldsyms, newsyms))
                if c.status == 'R':
                    # Compare occurrences across a rename using the new path.
                    oldrefs = [replace(r, path=c.path) for r in renamed_refs]
                refs.extend(added_references(oldrefs, newrefs))
                additions = {k: v for k,
                             v in newsyms.items() if k not in oldsyms}
                if additions:
                    defs.setdefault(newmod, {}).update(additions)
                dumps[newmod] = newdumps
            if c.status == 'A' and c.path.endswith('.py') and (cw004._DJANGO.match(c.path) or 'versions' in c.path.split('/')[:-1]):
                try:
                    source = tip_snap.read(c.path)
                except git.SkippedBlob:
                    source = None
                if source is not None:
                    migrations[c.path] = source
        api = {module: [change for change in items
                        if change.kind != 'removed' or (not tip_index.is_open(module)
                            and tip_index.resolve(module, change.qualname).status != 'valid')]
               for module, items in api.items()}
        return BranchSummary(
            '', sha, base, tuple(roots), tuple(changes),
            {module: tuple(items)
             for module, items in api.items()}, tuple(refs),
            defs, frozenset(redefined), migrations,
            frozenset(module for module, items in api.items() if items),
            frozenset(ref.module for ref in refs),
        )

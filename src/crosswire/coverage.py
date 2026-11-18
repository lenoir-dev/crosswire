"""Collect deterministic coverage gaps from user-visible Git states."""

from . import git
from .lang.base import Reason, Source
from .lang.python.coverage import _sites  # T21 compatibility hook



def inspect(repo, commits, roots=None, analysis=None):
    """Count distinct (path, line, construct) sites, excluding internal trials."""
    if analysis is None:
        return {}
    sites = {}
    requested = set(commits)

    def add(category, path, line, construct):
        sites.setdefault(category, set()).add((path, line, construct))

    contexts = set(analysis.observed) | set(analysis.consulted) | set(analysis.candidates) | set(analysis.changed)
    for commit, source_roots in sorted(contexts):
        if commit not in requested:
            continue
        index = analysis.index(commit, source_roots)
        refs = analysis.observed.get((commit, source_roots), ())
        # Resolve only references that participated in this run. External modules
        # are outside the supported analysis, rather than evidence of a gap.
        unresolved = []
        for ref in sorted(refs, key=lambda r: (r.path, r.line, r.module, r.name, repr(r.call))):
            result = index.resolve_use(ref)
            if result.status == 'unknown' and result.reason != Reason.EXTERNAL:
                unresolved.append((ref, index.adapter.coverage_reason(result)))
        paths = (analysis.changed.get((commit, source_roots), set())
                 | analysis.consulted.get((commit, source_roots), set())
                 | analysis.candidates.get((commit, source_roots), set())
                 | {ref.path for ref in refs})
        entries = git.entries_for_paths(repo, commit, paths)
        file_refs = {}
        for path in sorted(paths):
            entry = entries.get(path)
            if entry is None:
                continue
            if entry[0] == '160000':
                add('submodule', path, 1, 'submodule not analyzed')
                continue
            for gap in index.adapter.path_gaps(path, path in analysis.changed_paths):
                add(gap.category, gap.span.path, gap.span.line, gap.detail)
            if not index.adapter.claims(path):
                continue
            try:
                source = git.read_blob(repo, entry[1])
            except git.SkippedBlob as exc:
                add(exc.reason, path, 1, exc.reason)
                continue
            if source is None:
                continue
            namespaces = index.adapter.namespaces_of(path, index.context)
            module = namespaces[0] if namespaces else None
            gaps, present_refs = index.adapter.coverage_sites(Source(path, source, module),
                                                             index.context, extractor=_sites)
            file_refs[path] = present_refs
            for category, line, construct in gaps:
                if category not in ('parse_failure', 'non_utf8') and path not in analysis.changed_paths:
                    continue
                add(category, path, line, construct)
                if category == 'parse_failure':
                    analysis.warn_parse(path, commit)
        for ref, reason in unresolved:
            matches = [present for present in file_refs.get(ref.path, ())
                       if (present.module, present.name, present.call) == (ref.module, ref.name, ref.call)]
            if not matches:
                continue
            line = min(matches, key=lambda present: (abs(present.line - ref.line), present.line)).line
            add(f'unknown_resolution:{reason}', ref.path, line, f'{ref.module}.{ref.name}')
    return {category: {'count': len(items), 'examples': [f'{p}:{line}: {kind}' for p, line, kind in sorted(items)[:5]]}
            for category, items in sorted(sites.items())}


def text_lines(coverage, limitations, limits=None):
    """Render coverage and every category, including gaps alongside search bounds."""
    lines = []
    if coverage == 'bounded':
        lines.append(f"Coverage: bounded ({', '.join((limits or {}).get('hit', ()))}) — unchecked combinations are not proven safe.")
    elif coverage == 'partial':
        lines.append('Coverage: partial — some sites could not be analyzed.')
    for category, detail in sorted((limitations or {}).items()):
        lines.append(f"Limitation: {category}: {detail['count']} site(s)" +
                     (f" ({'; '.join(detail['examples'])})" if detail['examples'] else ''))
    return lines

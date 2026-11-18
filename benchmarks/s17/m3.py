"""Frozen M3 identity subtraction and eligibility, independent of detector output."""
from dataclasses import dataclass, replace


SUPPORTED = frozenset({"reportAttributeAccessIssue","reportCallIssue","reportMissingImports"})


@dataclass(frozen=True, order=True)
class Identity:
    rule: str
    path: str
    symbol: str
    occurrence: str
    root_cause: str


@dataclass(frozen=True)
class Observation:
    diagnostics: tuple
    complete: bool = True
    environment_failure: bool = False
    ambiguous: bool = False
    supported: tuple | None = None


@dataclass(frozen=True)
class Delta:
    status: str
    new: tuple = ()
    reason: str | None = None


def delta(baseline, state, path_map=None):
    mapping = path_map or {}
    if len(set(mapping.values())) != len(mapping):
        return Delta("unlabelled",reason="ambiguous-path-map")
    for observation in (baseline,state):
        if observation.environment_failure:return Delta("unlabelled",reason="environment-failure")
        if not observation.complete:return Delta("unlabelled",reason="incomplete-coverage")
        if observation.ambiguous or any(not isinstance(d,Identity) for d in observation.diagnostics):
            return Delta("unlabelled",reason="ambiguous-identity")
    old={replace(d,path=mapping.get(d.path,d.path)) for d in baseline.diagnostics}
    return Delta("complete",tuple(sorted(set(state.diagnostics)-old)))


def label(baseline, tips, integrated, path_maps=None):
    mappings=path_maps or {}
    for name,tip in tips.items():
        change=delta(baseline,tip,mappings.get(name))
        if change.status!="complete":return {"eligible":False,"label":"unlabelled","reason":change.reason,"diagnostics":()}
        if change.new:return {"eligible":False,"label":"unlabelled","reason":"new-tip-diagnostic","diagnostics":()}
    change=delta(baseline,integrated,mappings.get("integrated"))
    if change.status!="complete":return {"eligible":False,"label":"unlabelled","reason":change.reason,"diagnostics":()}
    supported=set(integrated.supported) if integrated.supported is not None else {d for d in change.new if d.rule in SUPPORTED}
    if any(d not in supported for d in change.new):
        return {"eligible":False,"label":"unlabelled","reason":"new-unsupported-diagnostic","diagnostics":()}
    return {"eligible":True,"label":"positive" if change.new else "control","reason":None,"diagnostics":change.new}


def minimal_attribution(baseline, states, branches, diagnostic, path_maps=None):
    mappings=path_maps or {};full=frozenset(branches)
    subsets=[full,*[full-{branch} for branch in full]]
    changes=[]
    for subset in subsets:
        if subset not in states:return None
        change=delta(baseline,states[subset],mappings.get(subset))
        if change.status!="complete":return None
        changes.append(diagnostic in change.new)
    return changes[0] and not any(changes[1:])

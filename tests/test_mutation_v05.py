"""Pre-freeze mutation selector/renderer checks; no upstream or holdout inputs."""
from benchmarks.mutation_v05.render import select_sites, render
import os
from pathlib import Path
import tempfile

import pytest


FILES={'pkg/__init__.py':'from .api import f as f\n',
       'pkg/api.py':'def f(value: int) -> int:\n    return value\n',
       'tests/test_api.py':'import pkg.api as api\nassert api.f(1) == 1\n'}
SPEC={'id':'synthetic','url':'https://example.invalid/synthetic','sha':'a'*40,'roots':['pkg']}


def test_seeded_site_selection_is_input_order_independent():
    one=select_sites(FILES,SPEC,'seed')
    assert one==select_sites(dict(reversed(list(FILES.items()))),SPEC,'seed')
    assert all(not s['path'].startswith('tests/') for s in one)
    assert sum(s['kind']=='function' for s in one)==1


def test_class_rename_updates_explicit_exports_and_forward_annotations():
    files={'pkg/api.py':'__all__ = ["Thing"]\nclass Thing:\n    def copy(self) -> "Thing":\n        return Thing()\n'}
    site=next(s for s in select_sites(files,SPEC,'seed') if s['kind']=='class')
    source=render(files,site,'rename','scenario')['branches']['A']['pkg/api.py']
    assert "'Thing_mutated'" in source and 'return Thing_mutated()' in source


def test_rename_updates_existing_qualified_uses_and_preserves_import_alias():
    site=next(s for s in select_sites(FILES,SPEC,'seed') if s['kind']=='function')
    result=render(FILES,site,'rename','scenario')
    assert 'def f_mutated(' in result['branches']['A']['pkg/api.py']
    assert 'api.f_mutated(1)' in result['branches']['A']['tests/test_api.py']
    assert 'f_mutated as f' in result['branches']['A']['pkg/__init__.py']
    assert result['base']==FILES


def test_three_controls_and_nway_topology_are_declared_by_renderer():
    site=next(s for s in select_sites(FILES,SPEC,'seed') if s['kind']=='function')
    for control in ('compatible','unrelated','coordinated'):
        assert render(FILES,site,'rename',control)['control']==control
    assert len(render(FILES,site,'conjunctive','scenario')['branches'])==3
    assert len(render(FILES,site,'fix_by_third','scenario')['branches'])==3
    assert len(render(FILES,site,'five_mix','scenario')['branches'])==5


def test_augmented_fallback_contains_the_actual_original_body():
    site=next(s for s in select_sites(FILES,SPEC,'seed') if s['kind']=='function')
    case=render(FILES,site,'conjunctive','scenario')
    assert case['augmentation'] and any(v==FILES['pkg/api.py'] for p,v in case['base'].items() if p not in FILES)


def test_arity_updates_existing_calls_but_new_consumer_keeps_original_shape():
    site=next(s for s in select_sites(FILES,SPEC,'seed') if s['kind']=='function')
    case=render(FILES,site,'arity','scenario')
    assert '_mutation_required: object' in case['branches']['A']['pkg/api.py']
    assert '_mutation_required=None' in case['branches']['A']['tests/test_api.py']
    assert '_mutation_required' not in case['branches']['B']['mutation_consumer.py']


@pytest.mark.parametrize('family,expected',[('rename','positive'),('delete','positive'),('arity','positive'),
    ('conjunctive','positive'),('fix_by_third','control'),('five_mix','positive'),
    ('open_dynamic','control'),('open_wildcard','control')])
def test_synthetic_m3_labels_and_controls_before_freeze(tmp_path,family,expected):
    python=os.environ.get('MUT_ORACLE_PYTHON')
    if not python:pytest.skip('Explicit pinned mutation oracle needed for synthetic pre-freeze integration')
    from conformance import git
    from benchmarks.s17.m3 import label
    from benchmarks.s17.oracle import observe
    from benchmarks.s17.identity import module_of
    site=next(s for s in select_sites(FILES,SPEC,'seed') if s['kind']=='function')
    for control in ('scenario','compatible','unrelated','coordinated'):
        rendered=render(FILES,site,family,control)
        repo=tmp_path/control/'repo'
        target,tips=git.build(repo,{'base':{p:s.encode() for p,s in rendered['base'].items()},
            'branches':[{'id':n,'files':{p:None if s is None else s.encode() for p,s in f.items()}} for n,f in rendered['branches'].items()]})
        full=git.integrate(repo,target,tips,list(tips))
        states={'target':target,**tips,'integrated':full}
        files={n:{p:b.decode() for p,b in git.files_at(repo,c).items() if p.endswith('.py')} for n,c in states.items()}
        include=sorted(set().union(*(set(v) for v in files.values())))
        known={module_of(p):p for p in include}
        observations={n:observe(f,tmp_path/control/n,python,known_modules=known,include=include)[0] for n,f in files.items()}
        result=label(observations['target'],{n:observations[n] for n in tips},observations['integrated'])
        assert result['label']==(expected if control=='scenario' else 'control'),(family,control,result)

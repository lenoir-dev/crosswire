"""Fast structural controls for the T24 fixture, independent of Crosswire."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    't24_fixture', Path(__file__).parents[1] / 'benchmarks/t24_blocked_plan.py')
t24 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t24)


@pytest.mark.parametrize('kind,safe,blocked', [('a', 21, 9), ('b', 22, 8)])
def test_manifest_is_deterministic_and_split_is_structural(monkeypatch, kind, safe, blocked):
    def no_oracle(*args, **kwargs):
        raise AssertionError('pure fixture generation/checking must not run an oracle')
    monkeypatch.setattr(t24.subprocess, 'run', no_oracle)
    first = t24.fixture_spec(kind)
    assert t24.canonical(first) == t24.canonical(t24.fixture_spec(kind))
    checked = t24.structural_check(first)
    assert (len(checked['safe']), len(checked['blocked'])) == (safe, blocked)
    assert checked['first_party_consumers'] == 80
    assert checked['shared_safe_regions'] == ([f'value_{i}' for i in range(7)] if kind == 'a' else [])


@pytest.mark.parametrize('kind', ['a', 'b'])
def test_materialized_commit_ids_do_not_depend_on_local_path(tmp_path, kind):
    manifest = t24.fixture_spec(kind)
    first = t24.materialize(manifest, tmp_path / 'first' / 'repo')
    second = t24.materialize(manifest, tmp_path / 'different path' / 'repo')
    assert first == second
    assert len(first['heads']) == 30
    assert t24.git(tmp_path / 'first' / 'repo', 'ls-files').count(b'\n') == 1000


def test_structural_check_rejects_a_hidden_break_in_the_safe_prefix():
    manifest = t24.fixture_spec('a')
    manifest['branches'][0]['edits'] = {'providers/api_0.py': 'keep = 0\n'}
    with pytest.raises(AssertionError):
        t24.structural_check(manifest)


def test_structural_check_rejects_overlapping_shared_edit_context():
    manifest = t24.fixture_spec('a')
    manifest['base']['shared.py'] = manifest['base']['shared.py'].replace(t24.GAP, '')
    with pytest.raises(AssertionError):
        t24.structural_check(manifest)

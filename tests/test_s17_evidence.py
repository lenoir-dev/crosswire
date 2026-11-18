"""Fast evidence integrity checks; never clone or rerun a measured checker."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from benchmarks.s17.run import FREEZE, ROOT, observation_from, verify_freeze
from benchmarks.s17.m3 import label


def selections():
    return sorted((ROOT/'docs/validation').glob('s17-*/selection.json'))


@pytest.fixture
def cohorts():
    # Extracted archives contain s17-natural/, s17-extension/, ... at the root.
    # Explicit configuration overrides locally present in-repo evidence.
    directory=Path(os.environ.get('CROSSWIRE_EVIDENCE_DIR', ROOT/'docs/validation')).expanduser()
    paths=[directory/p.parent.name/'results.json' for p in selections()]
    if not any(p.is_file() for p in paths):
        pytest.skip('S17 evidence absent; set CROSSWIRE_EVIDENCE_DIR to the extracted archive')
    assert all(p.is_file() for p in paths), 'Incomplete S17 evidence archive'
    return paths


def test_committed_selections_match_aggregate_pins():
    aggregate=json.loads((ROOT/'docs/validation/s17-results.json').read_text())
    paths=selections()
    assert len(paths)==5
    for path in paths:
        selected=json.loads(path.read_text())
        assert aggregate['inputs_sha256'][path.relative_to(ROOT).as_posix()]==hashlib.sha256(path.read_bytes()).hexdigest()
        assert selected['apparatus_freeze_sha256']==hashlib.sha256(FREEZE.read_bytes()).hexdigest()
        expected=[(r['id'],c['merge']) for r in selected['repositories'] for c in r['cases']]
        assert len(expected)==len(set(expected))==selected['selected_cases']
        assert all(c['target'] not in c['parents'] and len(set(c['parents']))==2
                   for r in selected['repositories'] for c in r['cases'])


def test_published_apparatus_still_equals_its_pre_label_freeze():
    verify_freeze()
    assert hashlib.sha256(FREEZE.read_bytes()).hexdigest() == '5e7dc0bbedbc88d55dec3fb3767322b1f2cf991d30d5b2016ecebb5e7a1e2170'


def test_every_preregistered_merge_has_exactly_one_immutable_case_record(cohorts):
    aggregate=json.loads((ROOT/'docs/validation/s17-results.json').read_text())
    case_pins={p['path']:p['sha256'] for p in aggregate['cases']}
    for path in cohorts:
        result=json.loads(path.read_text())
        selection=ROOT/'docs/validation'/path.parent.name/'selection.json'
        selected=json.loads(selection.read_text())
        relative='docs/validation/'+path.parent.name+'/results.json'
        assert aggregate['inputs_sha256'][relative]==hashlib.sha256(path.read_bytes()).hexdigest()
        assert result['selection_sha256']==hashlib.sha256(selection.read_bytes()).hexdigest()
        expected={(r['id'],c['merge']) for r in selected['repositories'] for c in r['cases']}
        actual=[(c['repository'],c['merge']) for c in result['cases']]
        assert len(actual)==len(set(actual)) and set(actual)==expected
        assert all(result[k] for k in ('source_stable','oracle_stable','apparatus_stable'))
        for case in result['cases']:
            assert case['target'] not in case['parents'] and len(set(case['parents']))==2
            archived=path.parent/'cases'/case['repository']/(case['merge']+'.json')
            relative='docs/validation/'+path.parent.name+'/cases/'+case['repository']+'/'+case['merge']+'.json'
            assert hashlib.sha256(archived.read_bytes()).hexdigest()==case_pins[relative]
            assert json.loads(archived.read_text())==case


def test_recorded_controls_rederive_from_oracle_identities_without_detector_output(cohorts):
    eligible=0
    for path in cohorts:
        for case in json.loads(path.read_text())['cases']:
            if not case['eligible']:
                assert case['label']=='unlabelled' and case['exclusion']
                continue
            eligible+=1
            evidence=case['oracle']
            observed={name:observation_from(value['identity_observation']) for name,value in evidence.items()}
            expected=label(observed['target'],{n:observed[n] for n in ('A','B')},observed['integrated'],case['path_maps'])
            assert expected['eligible'] and expected['label']==case['label']
            assert set(evidence)=={'target','A','B','integrated'}
            assert all(e['version']=='1.1.407' for e in evidence.values())
    assert eligible


def assert_portable(files):
    forbidden=('/Users/','/private/','/tmp/','/opt/homebrew/','/var/folders/')
    for path in files:
        text=path.read_text()
        assert not any(value in text for value in forbidden),path.name


def test_committed_manifests_do_not_publish_machine_local_paths():
    assert_portable([FREEZE, ROOT/'docs/validation/s17-results.json', *selections(),
                     *(ROOT/'docs/validation').glob('s17-*/policy.json')])


def test_evidence_does_not_publish_machine_local_paths(cohorts):
    assert_portable([p for result in cohorts for p in result.parent.rglob('*.json')])

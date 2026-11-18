"""Mutation publication pins always run; external D-Ev1 journals are optional."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from benchmarks.mutation_v05.run import ROOT, verify


def read(name):return json.loads((ROOT/'docs/validation'/name).read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def test_original_pre_label_freeze_and_post_label_correction_pins_are_separate():
    verify()
    result=read('mut-v05.json');audit=read('mut-v05-m2-audit.json')
    assert result['stratum']=='mutation' and result['development_only']
    assert result['scoring_audit']['manifest_sha256']==sha(ROOT/'docs/validation/mut-v05-m2-audit.json')
    for path,value in audit['code_sha256'].items():assert sha(ROOT/path)==value
    assert audit['mutation']['relabelled_cases']==audit['mutation']['detector_reruns']==audit['mutation']['oracle_reruns']==0
    assert audit['s17']['case_journals']==120 and audit['s17']['effect']=='none'
    assert audit['s17']['frozen_raw']==audit['s17']['m2_corrected']


def test_all_selected_cases_and_control_ratios_are_reported_without_substitution():
    result=read('mut-v05.json');selection=read('mut-v05-selection.json')
    selected={c['id'] for c in selection['cases']}
    assert len(selected)==len(selection['cases'])==result['cases']==192
    assert set(result['case_files_sha256'])==selected
    assert len(result['repositories'])==5
    for mode,values in result['modes'].items():
        assert sum(values['labels'].values())==192
        assert values['labels']['control']>=3*values['labels']['positive']
        micro=values['micro']
        assert micro['eligible_cases']+micro['unlabelled_cases']==192
        assert micro['gate_status']=='development only; no acceptance verdict'


def test_external_raw_and_corrected_journals_preserve_labels_and_detector_bytes():
    directory=Path(os.environ.get('CROSSWIRE_EVIDENCE_DIR',ROOT/'docs/validation/mut-v05-evidence')).expanduser()
    raw=directory/'frozen-raw-mutation/cases';corrected=directory/'m2-corrected-mutation/cases'
    if not raw.exists() and not corrected.exists():pytest.skip('Extract mutation evidence and set CROSSWIRE_EVIDENCE_DIR')
    result=read('mut-v05.json');audit=read('mut-v05-m2-audit.json')
    for identity,value in result['case_files_sha256'].items():
        old=raw/(identity+'.json');new=corrected/(identity+'.json')
        assert sha(old)==audit['mutation']['original_case_files_sha256'][identity]
        assert sha(new)==value
        before=json.loads(old.read_text());after=json.loads(new.read_text())
        for mode in result['modes']:
            assert before['modes'][mode]['label']==after['modes'][mode]['label']
            assert before['modes'][mode].get('detector')==after['modes'][mode].get('detector')

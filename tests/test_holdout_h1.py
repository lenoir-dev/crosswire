"""H1 synthetic tests only: never locate or inspect the real private holdout."""
import copy
import json
import os
from pathlib import Path

import pytest

from eval import run_holdout as h1


def test_journal_claim_is_durable_and_never_reopened(tmp_path):
    journal=h1.AttemptJournal.claim(tmp_path, {'n':2,'release':'0.5a'})
    journal.started(0, 'a'*64)
    journal.finished(0, 'a'*64, {'eligible':True,'tp':1})
    journal.started(1, 'b'*64)
    with pytest.raises(h1.AttemptConsumed):
        h1.AttemptJournal.claim(tmp_path, {'n':2,'release':'0.5a'})
    assert json.loads((tmp_path/'measurement-journal/000000.result.json').read_text())['row']['tp']==1
    assert not (tmp_path/'measurement-journal/000001.result.json').exists()
    for path in [tmp_path/'measurement-attempt.json',*list((tmp_path/'measurement-journal').iterdir())]:
        assert path.stat().st_mode & 0o777 == 0o600
    assert (tmp_path/'measurement-journal').stat().st_mode & 0o777 == 0o700


def test_journal_records_start_before_evaluation_and_fsyncs(tmp_path,monkeypatch):
    events=[];original=os.fsync
    monkeypatch.setattr(os,'fsync',lambda fd:(events.append('fsync'),original(fd))[-1])
    journal=h1.AttemptJournal.claim(tmp_path, {'n':1,'release':'0.5a'})
    journal.started(0,'c'*64)
    assert len(events)>=6 # file and containing directory, for every durable write
    with pytest.raises(FileExistsError):journal.started(0,'c'*64)


def test_partial_journal_does_not_invent_completed_rows(tmp_path):
    journal=h1.AttemptJournal.claim(tmp_path, {'n':3,'release':'0.5a'})
    journal.started(0,'d'*64);journal.finished(0,'d'*64,{'eligible':True,'tp':1})
    journal.started(1,'e'*64)
    rows,counts=journal.read(['d'*64,'e'*64,'f'*64])
    assert len(rows)==1
    assert counts=={'attempted_cases':2,'completed_cases':1,'failed_cases':1,'unattempted_cases':1}


def test_journal_rejects_row_without_matching_start(tmp_path):
    journal=h1.AttemptJournal.claim(tmp_path, {'n':1,'release':'0.5a'})
    journal.started(0,'d'*64);journal.finished(0,'d'*64,{'eligible':True})
    with pytest.raises(ValueError,match='identity'):
        journal.read(['e'*64])


def test_small_child_hides_complementary_totals_and_all_derived_metrics():
    value={'micro':{'tp':60,'fp':1,'fn':0,'precision':60/61},
           'by_rule':{'CW001':{'tp':20,'fp':1,'fn':0},'CW002':{'tp':20,'fp':0,'fn':0},'CW006':{'tp':20,'fp':0,'fn':0}},
           'repo_clustered95':{'repositories':4},'exclusions':{'oracle-ineligible':0},
           'source_sha256':'a'*64,'release':'0.5a'}
    original=copy.deepcopy(value)
    result=h1.suppress_small_cells(value)
    assert result['micro']==result['by_rule']==result['repo_clustered95']==result['exclusions']=={'status':'suppressed'}
    assert result['source_sha256']=='a'*64 and result['release']=='0.5a'
    assert value==original
    h1.assert_aggregate_only(result)


def test_small_exclusion_also_hides_all_linked_totals():
    value={'micro':{'tp':60,'fp':0,'fn':0,'eligible_cases':238,'unlabelled_cases':2},
           'by_rule':{},'exclusions':{'oracle-ineligible':2}}
    assert h1.suppress_small_cells(value)['micro']=={'status':'suppressed'}


def rows(tp=60,fp=0,fn=0):
    return [{'repository':str(n),'eligible':True,'tp':tp//4+(n<tp%4),
             'fp':fp if n==0 else 0,'fn':fn if n==0 else 0,'attribution':[],
             'by_rule':{},'unlabelled_predictions':[]} for n in range(4)]


def test_holdout_gates_are_micro_provisional_and_no_rule_verdict():
    result=h1.holdout_report(rows())
    assert result['micro']['precision_gate']=='provisional pass'
    assert result['micro']['recall_gate']=='pass'
    assert result['repo_clustered95']['status']=='not estimable'
    for cell in result['by_rule'].values():
        assert cell['precision_gate']==cell['recall_gate']=='not evaluated'
    h1.assert_aggregate_only(result)


def test_insufficient_and_interrupted_never_pass():
    assert h1.holdout_report(rows(tp=12))['micro']['precision_gate']=='insufficient data'
    interrupted=h1.holdout_report(rows(),interrupted=True)
    assert interrupted['micro']['precision_gate']==interrupted['micro']['recall_gate']=='insufficient data'
    assert interrupted['status']=='interrupted'


def test_micro_fail_and_recall_threshold_are_separate():
    assert h1.holdout_report(rows(tp=60,fp=10))['micro']['precision_gate']=='fail'
    assert h1.holdout_report(rows(tp=48,fn=12))['micro']['recall_gate']=='pass'
    assert h1.holdout_report(rows(tp=47,fn=13))['micro']['recall_gate']=='fail'


def test_precision_point_alone_cannot_pass_wilson_gate():
    result=h1.holdout_report(rows(tp=20))['micro']
    assert result['precision']==1 and result['precision_wilson95'][0]<.9
    assert result['precision_gate']=='fail'
    assert h1.holdout_report(rows(tp=59,fp=1))['micro']['precision_gate']=='provisional pass'


def test_report_only_recovers_marker_created_before_journal_directory(tmp_path):
    h1._write_private(tmp_path/'measurement-attempt.json',{'n':2,'release':'0.5a'})
    rows_,counts=h1.AttemptJournal(tmp_path).read(['a'*64,'b'*64])
    assert rows_==[] and counts['unattempted_cases']==2
    with pytest.raises(h1.AttemptConsumed):
        h1.AttemptJournal.claim(tmp_path,{'n':2,'release':'0.5a'})


def test_case_cannot_be_reported_without_durable_start(tmp_path):
    journal=h1.AttemptJournal.claim(tmp_path,{'n':1,'release':'0.5a'})
    journal.finished(0,'a'*64,{'eligible':True})
    with pytest.raises(ValueError,match='without start'):journal.read(['a'*64])


def test_amendment_rejects_any_other_sealed_change(tmp_path):
    original=Path('docs/validation/holdout.sha256')
    amended=tmp_path/'amended.sha256'
    lines=original.read_text().replace('83874bcd5a21ab59da853f89d278576d9f2459435939826358161f3a06597593','0'*64)
    amended.write_text(lines)
    with pytest.raises(ValueError,match='H1'):
        h1.verify_h1_amendment(Path.cwd(),amended)


def test_export_allowlist_does_not_accept_case_ids_or_private_errors():
    for value in [{'status':'private-fixture-name'},{'error_type':'ValueError'},{'case_index':1}]:
        with pytest.raises(AssertionError):h1.assert_aggregate_only(value)


def test_report_inputs_need_only_sealed_files_not_case_repositories(tmp_path,monkeypatch):
    from eval.integrity import digest
    private=tmp_path/'private';private.mkdir()
    manifest=private/'manifest.json'
    manifest.write_text(json.dumps({'cases':[{'path':'deliberately-unavailable-case'}]}))
    seal=tmp_path/'synthetic.sha256';seal.write_text(digest(manifest)+'  private/manifest.json\n')
    monkeypatch.setattr(h1,'verify_seal',lambda *a:pytest.fail('Report must not reopen case repositories'))
    assert len(h1._recorded_inputs(private,tmp_path,seal)['cases'])==1
    manifest.write_text('{}')
    with pytest.raises(ValueError,match='hash mismatch'):h1._recorded_inputs(private,tmp_path,seal)

"""Pre-freeze matching/statistics controls; no natural corpus data."""
from benchmarks.s17.identity import identify_files
from benchmarks.s17.matching import match
from benchmarks.s17.metrics import aggregate, clustered


def test_emitted_wrong_rule_is_not_copied_from_oracle_type():
    base={'api.py':'def f(a): return a\n','use.py':'import api\napi.f()\n'}
    raw={'file':'use.py','rule':'reportCallIssue','range':{'start':{'line':1,'character':0}}}
    observation=identify_files(base,[raw],known_modules={'api':'api.py','use':'use.py'},files_analyzed=2)
    finding={'rule':'CW001','path':'use.py','line':2,'symbol':'api.f'}
    result=match([finding],observation.diagnostics,base,base,{'api':'api.py','use':'use.py'})
    assert (result['tp'],result['fp'],result['fn'])==(0,1,1)
    finding['rule']='CW002'
    result=match([finding,finding],observation.diagnostics,base,base,{'api':'api.py','use':'use.py'})
    assert (result['tp'],result['fp'],result['fn'])==(1,1,0)


def test_empty_cells_and_zero_findings_cannot_pass_a_gate():
    rows=[{'repository':str(i),'eligible':True,'tp':0,'fp':0,'fn':0} for i in range(5)]
    stats=aggregate(rows)
    assert stats['precision'] is None and stats['recall'] is None and stats['sample_status']=='insufficient data'
    assert stats['gate_status']=='development only; no acceptance verdict'
    assert clustered(rows)['precision'] is None
    assert clustered(rows[:4])['status']=='not estimable'

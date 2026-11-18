"""Published M2 contract, tested without any real mutation/holdout evidence."""
from benchmarks.s17.m3 import Identity
from benchmarks.s17.matching import match as frozen_match
from benchmarks.mut_v05_m2_audit import match


def fixture():
    base={'pkg/__init__.py':'class Thing: pass\n'}
    full={'mutation_consumer.py':'import pkg as api\napi.Thing\n'}
    known={'pkg':'pkg/__init__.py','mutation_consumer':'mutation_consumer.py'}
    diagnostic=Identity('reportMissingImports','mutation_consumer.py','pkg','import','missing-module')
    finding={'rule':'CW001','path':'mutation_consumer.py','line':2,'symbol':'pkg.Thing'}
    return base,full,known,diagnostic,finding


def test_inherited_bug_and_m2_module_file_only_correction():
    base,full,known,d,f=fixture()
    raw=frozen_match([f],[d],base,full,known)
    assert (raw['tp'],raw['fp'],raw['fn'])==(0,1,1)
    corrected=match([f],[d],base,full,known)
    assert (corrected['tp'],corrected['fp'],corrected['fn'])==(1,0,0)


def test_duplicate_module_findings_are_still_one_to_one():
    base,full,known,d,f=fixture();result=match([f,f],[d],base,full,known)
    assert (result['tp'],result['fp'],result['fn'])==(1,1,0)


def test_different_module_or_use_file_is_never_a_match():
    base,full,known,d,f=fixture()
    known['other']='other/__init__.py'
    wrong={**f,'symbol':'other.Thing'}
    result=match([wrong],[d],base,full,known)
    assert (result['tp'],result['fp'],result['fn'])==(0,1,1)


def test_same_missing_module_in_another_file_is_not_a_match():
    base,full,known,d,f=fixture()
    full['other_use.py']=full['mutation_consumer.py']
    result=match([{**f,'path':'other_use.py'}],[d],base,full,known)
    assert (result['tp'],result['fp'],result['fn'])==(0,1,1)


def test_non_py2_results_are_identical_to_frozen_matcher():
    known={'pkg':'pkg.py','use':'use.py'};base={'pkg.py':'def f(x): return x\n'}
    full={'use.py':'import pkg\npkg.f()\n'}
    finding={'rule':'CW002','path':'use.py','line':2,'symbol':'pkg.f'}
    d=Identity('reportCallIssue','use.py','pkg.f','call','root')
    assert match([finding],[d],base,full,known)==frozen_match([finding],[d],base,full,known)


def test_two_distinct_missing_modules_in_same_use_file_match_independently():
    base,full,known,d,f=fixture()
    known['other']='other.py';base['other.py']='class Thing: pass\n'
    other=Identity('reportMissingImports','mutation_consumer.py','other','second-import','other-root')
    result=match([f,{**f,'symbol':'other.Thing'}],[d,other],base,full,known)
    assert (result['tp'],result['fp'],result['fn'])==(2,0,0)
    assert {m['diagnostic'].symbol for m in result['matches']}=={'pkg','other'}


def test_outside_oracle_scope_is_unlabelled_not_false_positive():
    base,full,known,d,f=fixture()
    result=match([{**f,'path':'outside.py'}],[d],base,full,known)
    assert (result['tp'],result['fp'],result['fn'])==(0,0,1)
    assert result['unlabelled']==[{'finding':{**f,'path':'outside.py'},'reason':'outside-oracle-scope'}]

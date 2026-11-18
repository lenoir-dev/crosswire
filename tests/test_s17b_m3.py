"""Synthetic observations exercise exact frozen M3 adaptation, no oracle run."""
from benchmarks.s17.m3 import Identity,Observation
from benchmarks.s17b.pipeline import m3_contract


def states():return {n:Observation(()) for n in ('B_A','H_A','B_B','H_B','L','A_L','B_L','I_AB')}
def diagnostic():return Identity('reportCallIssue','use.py','api.f','call','new-root')


def test_two_green_own_tips_new_common_integration_positive():
    observed=states();observed['I_AB']=Observation((diagnostic(),))
    result=m3_contract(observed,{})
    assert result['eligible'] and result['label']=='positive'


def test_normalization_repairs_tip_but_own_base_check_still_excludes():
    observed=states();observed['H_A']=Observation((diagnostic(),))
    assert m3_contract(observed,{})['reason'].startswith('own-base')


def test_normalization_can_add_new_error_and_common_check_excludes():
    observed=states();observed['A_L']=Observation((diagnostic(),));observed['I_AB']=observed['A_L']
    assert m3_contract(observed,{})['label']=='unlabelled'


def test_non_green_baseline_old_identity_is_subtracted_in_both_checks():
    old=Identity('reportCallIssue','old.py','api.g','old','old-root')
    observed={n:Observation((old,)) for n in states()}
    observed['I_AB']=Observation((old,diagnostic()))
    assert m3_contract(observed,{})['label']=='positive'


def test_incomplete_and_ambiguous_never_controls():
    for bad in (Observation((),complete=False),Observation((),ambiguous=True),Observation((),environment_failure=True)):
        observed=states();observed['I_AB']=bad
        assert m3_contract(observed,{})['label']=='unlabelled'

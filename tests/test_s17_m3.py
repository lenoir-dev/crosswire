"""M3 oracle policy tests written before its implementation and any labels."""
from dataclasses import replace

import pytest

from benchmarks.s17.m3 import Identity, Observation, delta, label, minimal_attribution


def diag(symbol="api.f", occurrence="call-one", rule="reportCallIssue", path="use.py", root="call-root"):
    return Identity(rule,path,symbol,occurrence,root)


def observation(*diagnostics, **kwargs):
    return Observation(tuple(diagnostics), **kwargs)


def test_baseline_errors_do_not_require_a_green_target_and_line_shifts_keep_identity():
    old=diag()
    baseline=observation(old)
    assert delta(baseline,observation(old)).new==()
    result=label(baseline,{"A":observation(old),"B":observation(old)},observation(old))
    assert result["label"]=="control" and result["eligible"]


def test_removing_one_error_cannot_mask_a_new_error_with_the_same_message_category():
    baseline=observation(diag())
    new=diag(occurrence="different-call",root="different-root")
    assert delta(baseline,observation(new)).new==(new,)
    assert label(baseline,{"A":observation(),"B":baseline},observation(new))["label"]=="positive"


def test_new_tip_diagnostic_makes_the_entire_case_ineligible():
    baseline=observation()
    result=label(baseline,{"A":observation(diag()),"B":baseline},observation(diag()))
    assert not result["eligible"] and result["label"]=="unlabelled" and result["reason"]=="new-tip-diagnostic"


@pytest.mark.parametrize("bad",[observation(complete=False),observation(environment_failure=True),
                              observation(ambiguous=True),observation(None)])
def test_ambiguous_incomplete_or_environment_states_are_never_controls(bad):
    assert delta(observation(),bad).status=="unlabelled"
    assert label(observation(),{"A":observation(),"B":observation()},bad)["label"]=="unlabelled"


def test_baseline_uncertainty_also_prevents_labeling():
    assert label(observation(complete=False),{"A":observation(),"B":observation()},observation())["label"]=="unlabelled"


def test_path_mapping_is_explicit_and_one_to_one():
    old=diag(path="old/use.py")
    new=replace(old,path="new/use.py")
    assert delta(observation(old),observation(new),{"old/use.py":"new/use.py"}).new==()
    assert delta(observation(old),observation(new)).new==(new,)
    assert delta(observation(old),observation(new),{"a.py":"same.py","b.py":"same.py"}).status=="unlabelled"


def test_duplicate_diagnostics_of_the_same_root_do_not_multiply_positives():
    new=diag()
    result=label(observation(),{"A":observation(),"B":observation()},observation(new,new))
    assert result["label"]=="positive" and result["diagnostics"]==(new,)


def test_unmapped_or_changed_symbol_and_root_are_distinct_identities():
    old=diag()
    for new in (replace(old,symbol="api.other"),replace(old,root_cause="other-root")):
        assert delta(observation(old),observation(new)).new==(new,)


def test_new_unsupported_error_is_unlabelled_not_a_negative_or_supported_positive():
    new=diag(rule="reportArgumentType")
    result=label(observation(),{"A":observation(),"B":observation()},observation(new))
    assert result["label"]=="unlabelled" and result["reason"]=="new-unsupported-diagnostic"


def test_attribution_compares_the_same_root_delta_not_checker_exit_status():
    baseline_error=diag(root="baseline-root",occurrence="baseline-call")
    new=diag(root="new-root",occurrence="new-call")
    baseline=observation(baseline_error)
    states={frozenset():baseline,frozenset({"A"}):baseline,frozenset({"B"}):baseline,
            frozenset({"A","B"}):observation(baseline_error,new)}
    assert minimal_attribution(baseline,states,{"A","B"},new) is True
    states[frozenset({"A"})]=observation(baseline_error,new)
    assert minimal_attribution(baseline,states,{"A","B"},new) is False
    states[frozenset({"A"})]=observation(complete=False)
    assert minimal_attribution(baseline,states,{"A","B"},new) is None


def test_multiple_calls_without_a_unique_mapping_are_excluded():
    baseline=observation(diag())
    current=observation(diag(),diag(occurrence="call-two"),ambiguous=True)
    assert delta(baseline,current).status=="unlabelled"

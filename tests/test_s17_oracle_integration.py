"""Pinned-checker synthetic oracle tests, before natural S17 labels."""
import os
import sys

from benchmarks.s17.oracle import observe
from benchmarks.s17.m3 import label


def test_non_green_baseline_can_have_a_new_supported_interaction(tmp_path):
    python=os.environ.get("S17_ORACLE_PYTHON",sys.executable)
    api="def f(a: int, b: int) -> int:\n    return a\n\ndef g(a: int) -> int:\n    return a\n"
    base={"api.py":api,"old_use.py":"import api\napi.f(1)\n"}
    left={**base,"api.py":api.split('\ndef g')[0]}
    right={**base,"new_use.py":"import api\napi.g(1)\n"}
    full={**left,"new_use.py":right['new_use.py']}
    known={"api":"api.py","old_use":"old_use.py","new_use":"new_use.py"}
    observations=[observe(files,tmp_path/name,python,known_modules=known,include=sorted(full))
                  for name,files in (("target",base),("A",left),("B",right),("integrated",full))]
    result=label(observations[0][0],{"A":observations[1][0],"B":observations[2][0]},observations[3][0])
    assert len(observations[0][0].diagnostics)==1
    assert result['eligible'] and result['label']=='positive' and len(result['diagnostics'])==1
    assert result['diagnostics'][0].symbol=='api.g'


def test_missing_dependency_and_invalid_syntax_stay_unlabelled(tmp_path):
    python=os.environ.get("S17_ORACLE_PYTHON",sys.executable)
    observation,evidence=observe({"use.py":"import never_installed_s17_dependency\n"},tmp_path/"missing",python,known_modules={"use":"use.py"},include=["use.py"])
    assert observation.environment_failure
    invalid,_=observe({"bad.py":"def broken(\n"},tmp_path/"syntax",python,known_modules={"bad":"bad.py"},include=["bad.py"])
    assert not invalid.complete

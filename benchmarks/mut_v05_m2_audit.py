"""Scoring-only M2 conformance audit; frozen labels/product runs stay untouched.

The inherited S17 matcher needs the diagnostic to be on the finding's line even
for PY-2. Frozen matching.md M2 instead specifies missing module + use-site file.
This adapter changes ONLY that key. It neither invokes nor imports the product.
"""
from collections import defaultdict
from benchmarks.s17.matching import bucket,oracle_type,match as frozen_match


def missing_module(symbol,known):
    return max((m for m in known if symbol==m or symbol.startswith(m+'.')),key=len,default=None)


def match(findings,diagnostics,base,integrated,known):
    module_findings=[];other_findings=[]
    for f in findings:
        if f.get('rule')=='CW001' and bucket('CW001',f.get('symbol') or '',base,integrated,known)=='PY-2':
            module_findings.append(f)
        else:other_findings.append(f)
    module_diagnostics=[];other_diagnostics=[]
    for d in diagnostics:
        (module_diagnostics if oracle_type(d,base,integrated,known)=='PY-2' else other_diagnostics).append(d)
    result=frozen_match(other_findings,other_diagnostics,base,integrated,known)
    groups=defaultdict(list)
    for d in module_diagnostics:
        groups[(d.path,missing_module(d.symbol,known))].append(d)
    remaining=set(groups)
    for f in module_findings:
        if f.get('path') not in integrated:
            result['unlabelled'].append({'finding':f,'reason':'outside-oracle-scope'});continue
        key=(f.get('path'),missing_module(f.get('symbol') or '',known))
        if key in remaining and key[1] is not None:
            remaining.remove(key)
            result['matches'].append({'finding':f,'type':'PY-2','diagnostic':groups[key][0]})
        else:
            result['false_positives'].append({'finding':f,'type':'PY-2','reason':'no oracle missing-module/use-file root (M2)'})
    for key in sorted(remaining):
        result['misses'].append({'type':'PY-2','diagnostics':groups[key],'reason':'no finding for oracle missing-module/use-file root (M2)'})
    result.update(tp=len(result['matches']),fp=len(result['false_positives']),fn=len(result['misses']))
    return result

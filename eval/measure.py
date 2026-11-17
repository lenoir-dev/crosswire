"""Detector execution and M2 matching, independent of oracle labelling."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

from .integrity import assert_case, git
from .metrics import aggregate, clustered, match
from .oracle import occurrence, reason_category

RULES = ('CW001', 'CW002', 'CW003', 'CW004', 'CW006')


def source_at(directory, revision, path):
    result = subprocess.run(['git','show',f'{revision}:{path}'],cwd=directory,capture_output=True,text=True)
    return result.stdout if result.returncode == 0 else ''


def modules(directory, revision):
    paths = git(directory, 'ls-tree', '-r', '--name-only', revision).splitlines()
    result = {}
    for path in paths:
        if not path.endswith('.py'):
            continue
        pieces = list(Path(path).with_suffix('').parts)
        if pieces[0] in {'src', 'lib'}:
            pieces.pop(0)
        if pieces[-1] == '__init__':
            pieces.pop()
        result['.'.join(pieces)] = path
    return result


def prediction_type(finding, directory, baseline, integrated):
    """Use the emitted rule and resolved symbol/module, never the case's type."""
    rule, symbol = finding['rule'], finding.get('symbol') or ''
    if rule == 'CW002':
        return 'PY-4', None
    if rule == 'CW006':
        return 'PY-5', None
    if rule != 'CW001':
        return None, None
    candidates = [name for name in baseline if symbol == name or symbol.startswith(name+'.')]
    module = max(candidates, key=len, default=symbol.rsplit('.',1)[0])
    if module not in integrated:
        return 'PY-2', module
    try:
        tree = ast.parse(source_at(directory, 'HEAD', integrated[module]))
        name = symbol[len(module)+1:].split('.')[0]
        if any(isinstance(n,ast.ImportFrom) and any(a.asname == name or a.asname is None and a.name == name for a in n.names) for n in ast.walk(tree)):
            return 'PY-3', None
        # Deleted re-export bindings remain identifiable in the baseline module.
        tree = ast.parse(source_at(directory, 'main', baseline[module]))
        if any(isinstance(n,ast.ImportFrom) and any((a.asname or a.name) == name for a in n.names) for n in ast.walk(tree)):
            return 'PY-3', None
    except (SyntaxError, KeyError):
        pass
    return 'PY-1', None


def diagnostics_for(case):
    if case['kind'] != 'positive' or not case.get('oracle_positive'):
        return []
    if 'diagnostics' in case:
        return case['diagnostics']
    result = {}
    for error in case['oracle']['integrated']['diagnostics']:
        if error.get('rule') not in {'reportMissingImports','reportAttributeAccessIssue','reportCallIssue'}:
            continue
        line = error['range']['start']['line']+1
        symbol = case['symbol']
        path=case['consumer']
        content=case['consumer_source']
        if Path(error['file']).name != case['consumer']:
            directory=Path(case['path'])
            paths=git(directory,'ls-tree','-r','--name-only',case['integrated']).splitlines()
            path=next((p for p in sorted(paths,key=len,reverse=True) if error['file'].endswith('/'+p) or error['file']==p),None)
            if path is None:
                raise AssertionError('Oracle diagnostic outside pinned tree')
            content=source_at(directory,case['integrated'],path)
            tree=ast.parse(content)
            aliases={}
            for n in ast.walk(tree):
                if isinstance(n,ast.Import):
                    aliases.update({a.asname or a.name:a.name for a in n.names})
                elif isinstance(n,ast.ImportFrom) and n.module and not n.level:
                    aliases.update({a.asname or a.name:n.module+'.'+a.name for a in n.names})
            sites=[n for n in ast.walk(tree) if isinstance(n,(ast.Call,ast.Attribute,ast.ImportFrom)) and n.lineno<=line<=getattr(n,'end_lineno',n.lineno)]
            expressions=[n.func if isinstance(n,ast.Call) else n for n in sites if isinstance(n,(ast.Call,ast.Attribute))]
            resolved=[]
            for expression in expressions:
                spelling=ast.unparse(expression)
                head,_,tail=spelling.partition('.')
                if head in aliases:resolved.append(aliases[head]+('.'+tail if tail else ''))
            if not resolved:
                for n in sites:
                    if isinstance(n,ast.ImportFrom) and n.module:
                        resolved.extend(n.module+'.'+a.name for a in n.names)
            if not resolved:
                raise AssertionError('Supported oracle identity needs explicit annotation')
            symbol=resolved[0]
        module = symbol.rsplit('.',1)[0] if case['type'] == 'PY-2' else None
        site = occurrence(content,line,symbol)
        key = (case['type'],path,module if module else symbol, None if module else site)
        entry = result.setdefault(key, {'type':case['type'],'path':path,'symbol':symbol,'module':module,'occurrence':site,'reasons':[], 'rule':'CW006' if case['type']=='PY-5' else 'CW002' if case['type']=='PY-4' else 'CW001'})
        reason = reason_category(error['message'])
        if reason not in entry['reasons']:
            entry['reasons'].append(reason)
    return list(result.values())


def evaluate(case, detector_python, source):
    row = {'repository':case.get('repository','unknown'),'eligible':bool(case.get('eligible')),'exclusion':case.get('exclusion'),'tp':0,'fp':0,'fn':0,'attribution':[], 'by_rule':{}}
    if not row['eligible']:
        return row
    directory = Path(case['path'])
    assert_case(case)
    diagnostics = diagnostics_for(case)
    command = [str(detector_python),'-m','crosswire','check','--repo',str(directory),'--target',case['target'],'--combined','--no-cache','--format','json',*case['tips']]
    def snapshot():
        files = {str(p.relative_to(directory)):(p.readlink().as_posix() if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest(),p.lstat().st_mode) for p in directory.rglob('*') if p.is_file() and '.git' not in p.relative_to(directory).parts}
        return (git(directory,'rev-parse','HEAD'),git(directory,'for-each-ref'),(directory/'.git/HEAD').read_bytes(),(directory/'.git/index').read_bytes(),files)
    before = snapshot()
    report, failure = None, None
    try:
        executed = subprocess.run(command,capture_output=True,text=True,env=os.environ | {'PYTHONPATH':str(source),'GIT_OPTIONAL_LOCKS':'0'},timeout=case.get('detector_timeout',60))
        if executed.returncode not in (0,1):
            failure = 'exit-error'
        else:
            report = json.loads(executed.stdout)
            if not isinstance(report,dict) or not isinstance(report.get('findings'),list):
                failure = 'invalid-output'
            elif any(not isinstance(f,dict) or not isinstance(f.get('rule'),str) or (f['rule'] in {'CW001','CW002','CW006'} and not (all(isinstance(f.get(k),str) for k in ('path','message','branch','symbol')) and isinstance(f.get('line'),int) and f['line']>0 and isinstance(f.get('culprits'),list) and all(isinstance(c,str) for c in f['culprits']))) for f in report['findings']):
                failure = 'invalid-output'
    except subprocess.TimeoutExpired:
        failure = 'timeout'
    except (json.JSONDecodeError,UnicodeError,OSError):
        failure = 'invalid-output'
    finally:
        assert snapshot() == before, 'Detector modified case repository'
    predictions, unlabelled = [], []
    if not failure:
        baseline = modules(directory,case['target'])
        integrated = modules(directory,case['integrated'])
        for finding in report['findings']:
            if finding['rule'] not in {'CW001','CW002','CW006'}:
                continue
            roots = case.get('oracle_roots',case['roots'])
            checked = finding['path']==case['consumer'] or any(finding['path']==root or finding['path'].startswith(root.rstrip('/')+'/') for root in roots)
            if not checked:
                unlabelled.append({'finding':finding,'reason':'outside-oracle-scope'})
                continue
            type_, module = prediction_type(finding,directory,baseline,integrated)
            content = source_at(directory,case['integrated'],finding['path'])
            claimed = sorted(finding['culprits'])
            trials = case.get('attribution_trials',[])
            trial = next((t for t in trials if t['branch']==finding['branch'] and sorted(t['culprits'])==claimed),None)
            attribution = trial.get('confirmed') if trial else None
            states=case.get('oracle_states',{})
            if states and finding['branch'] in case['tips'] and set(claimed)<=set(case['tips']):
                labels=set(claimed)|{finding['branch']}
                full=states.get('+'.join(sorted(labels)),{}).get('status')
                subsets=[states.get('+'.join(sorted((set(claimed)-{c})|{finding['branch']})),{}).get('status') for c in claimed]
                attribution=None if full not in {'pass','fail'} or any(s not in {'pass','fail'} for s in subsets) else full=='fail' and all(s=='pass' for s in subsets)
            predictions.append({'type':type_,'path':finding['path'],'module':module,'symbol':finding.get('symbol'),'occurrence':occurrence(content,finding['line'],finding.get('symbol') or ''),'rule':finding['rule'],'reason':reason_category(finding['message']),'attribution':attribution,'finding':finding})
    matched = match(predictions,diagnostics)
    for rule in RULES:
        hits = [m for m in matched['matches'] if m['prediction']['rule']==rule]
        row['by_rule'][rule] = {'tp':len(hits),'fp':sum(p['rule']==rule for p in matched['false_positives']),'fn':sum(d.get('rule')==rule for d in matched['misses']),'attribution':[m['attribution'] for m in hits]}
    row.update(tp=matched['tp'],fp=matched['fp'],fn=matched['fn'],attribution=[m['attribution'] for m in matched['matches']],reason_mismatches=matched['reason_mismatches'],misses=matched['misses'],false_positives=matched['false_positives'],unlabelled_predictions=unlabelled,readonly_verified=True,detector_failure=failure,report=report,command=command,family=case['family'],kind=case['kind'])
    return row


def report(rows):
    summary = {'micro':aggregate(rows),'repo_clustered95':clustered(rows),'by_rule':{}}
    for rule in RULES:
        subset = [{**row,**row.get('by_rule',{}).get(rule,{'tp':0,'fp':0,'fn':0,'attribution':[]}),
                   'unlabelled_predictions':[p for p in row.get('unlabelled_predictions',[]) if p['finding']['rule']==rule]} for row in rows]
        summary['by_rule'][rule] = aggregate(subset)
        summary['by_rule'][rule]['repo_clustered95'] = clustered(subset)
        summary['by_rule'][rule]['reason_category_mismatches'] = sum(len(row.get('reason_mismatches',[])) for row in rows) if rule=='CW002' else 0
    # Fixed vocabulary only. Free-text exclusions stay in private/public raw rows.
    summary['exclusions'] = {'oracle-ineligible':sum(not r['eligible'] for r in rows)}
    return summary

"""M1/M2 emitted-rule matching, distinct from M3's ground-truth labeling."""
import ast
from collections import defaultdict

from .identity import identify_files


RULES=('CW001','CW002','CW006')


def bucket(rule,symbol,base,integrated,known):
    if rule=='CW002':return 'PY-4'
    if rule=='CW006':return 'PY-5'
    module=max((m for m in known if symbol==m or symbol.startswith(m+'.')),key=len,default=None)
    if module and known[module] not in integrated:return 'PY-2'
    if module and known[module] in base:
        name=symbol[len(module)+1:]
        try:tree=ast.parse(base[known[module]])
        except (SyntaxError,ValueError):return None
        if any(isinstance(n,ast.ImportFrom) and any((a.asname or a.name)==name for a in n.names) for n in ast.walk(tree)):return 'PY-3'
    return 'PY-1'


def oracle_type(identity,base,integrated,known):
    if identity.rule=='reportMissingImports':return 'PY-2'
    if identity.rule=='reportCallIssue':return 'PY-4'
    module=max((m for m in known if identity.symbol.startswith(m+'.')),key=len,default=None)
    if module and known[module] in base:
        try:tree=ast.parse(base[known[module]])
        except (SyntaxError,ValueError):return None
        name=identity.symbol[len(module)+1:]
        definitions=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name]
        aliases=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and any((a.asname or a.name)==name for a in n.names)]
        if len(definitions)+len(aliases)>1:return 'PY-5'
    return bucket('CW001',identity.symbol,base,integrated,known)


def match(findings,diagnostics,base,integrated,known):
    groups=defaultdict(list)
    for d in diagnostics:
        type_=oracle_type(d,base,integrated,known)
        groups[(type_,d.path,d.symbol,d.root_cause)].append(d)
    remaining=set(groups);matches=[];fps=[];unlabelled=[]
    for finding in findings:
        if finding.get('rule') not in RULES:continue
        path=finding.get('path');symbol=finding.get('symbol') or ''
        if path not in integrated:
            unlabelled.append({'finding':finding,'reason':'outside-oracle-scope'});continue
        type_=bucket(finding['rule'],symbol,base,integrated,known)
        rule='reportMissingImports' if type_=='PY-2' else 'reportCallIssue' if type_=='PY-4' else 'reportAttributeAccessIssue'
        lines=integrated[path].splitlines();line=finding.get('line',0)
        column=len(lines[line-1])-len(lines[line-1].lstrip()) if 0<line<=len(lines) else 0
        raw={'file':path,'rule':rule,'range':{'start':{'line':line-1,'character':column}}}
        predicted=identify_files(integrated,[raw],known_modules=known,files_analyzed=len(integrated))
        candidates=[p for p in predicted.diagnostics if p is not None]
        chosen=None
        for group in sorted(remaining):
            if group[0]!=type_ or group[1]!=path:continue
            for p in candidates:
                if any(p.symbol==d.symbol and (type_=='PY-2' or p.occurrence==d.occurrence) for d in groups[group]):chosen=group;break
            if chosen:break
        if chosen is None:fps.append({'finding':finding,'type':type_,'reason':'no attributable oracle diagnostic at emitted type/file/symbol/occurrence'})
        else:
            remaining.remove(chosen);matches.append({'finding':finding,'type':type_,'diagnostic':groups[chosen][0]})
    return {'tp':len(matches),'fp':len(fps),'fn':len(remaining),'matches':matches,'false_positives':fps,
            'misses':[{'type':g[0],'diagnostics':groups[g],'reason':'no matching detector finding'} for g in sorted(remaining)],
            'unlabelled':unlabelled}

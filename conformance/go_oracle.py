"""Offline Go 1.27.1 build oracle; S19a's unchanged go/types position helper.

The historical census's duplicate-import mapping is superseded here by the frozen
GO-4 clarification. English diagnostic text is retained but never categorizes it.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from .git import environment as git_environment, write_files
from .oracle import KitBug
from .render.go import MODULE

PIN='go1.27.1'
TARGET={'GOOS':'darwin','GOARCH':'arm64'}
HELPER=Path(__file__).with_name('go_categories.go')
DUPLICATES={'DuplicateDecl','DuplicateMethod','DuplicateFieldAndMethod'}


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment(cache):
    env={k:v for k,v in git_environment().items() if not k.startswith(('GO','CGO'))}
    env.update(TARGET,GOENV='off',GOTOOLCHAIN='local',GOWORK='off',CGO_ENABLED='0',
               GOFLAGS='-mod=readonly',GOCACHE=str(cache/'gocache'),GOMODCACHE=str(cache/'modules'),
               GOPATH=str(cache/'gopath'),GOPROXY='off',GOSUMDB='off',GOVCS='*:off',GOTELEMETRY='off',
               GONOPROXY='',GONOSUMDB='',GOPRIVATE='',GOMAXPROCS='2')
    return env


def json_stream(raw):
    decoder=json.JSONDecoder();result=[];raw=raw.strip()
    while raw:
        value,end=decoder.raw_decode(raw);result.append(value);raw=raw[end:].lstrip()
    return result


def compiler_positions(text):
    return [{'path':p.strip().removeprefix('./'),'line':int(line),'column':int(column)}
            for p,line,column in re.findall(r'(?m)^\s*(.+?\.go):(\d+):(\d+):',text)]


def same_site(d,p):
    if d['path']!=p['path']:return False
    point=(p['line'],p['column']);start=(d.get('start_line',0),d.get('start_column',0));end=(d.get('end_line',0),d.get('end_column',0))
    return point==(d['line'],d['column']) or start!=(0,0) and start<=point<end


class GoOracle:
    def __init__(self,go,cache):
        self.go=str(Path(go).absolute());self.cache=Path(cache).resolve();self.cache.mkdir(parents=True,exist_ok=True)
        self.env=environment(self.cache)
        info=self.execute([self.go,'env','-json','GOVERSION','GOROOT','GOHOSTOS','GOHOSTARCH'],self.cache)
        if info.returncode:raise KitBug('Go toolchain unavailable')
        try:self.info=json.loads(info.stdout)
        except ValueError as e:raise KitBug('Invalid Go environment output') from e
        if self.info.get('GOVERSION')!=PIN:raise KitBug('Go toolchain must be '+PIN)
        self.goroot=Path(self.info['GOROOT']);self.helper=self.cache/'category-helper'
        self.codes_path=self.goroot/'src/internal/types/errors/code_string.go'
        self.names={int(n):name for name,n in re.findall(r'x\[([A-Za-z_][A-Za-z_0-9]*)\s*-\s*(-?\d+)\]',self.codes_path.read_text())}
        if not self.names:raise KitBug('Pinned go/types code table unavailable')
        # The helper executes on the host; the semantic builds below always use
        # the fixed target. go/types Sizes uses that same fixed target GOARCH.
        host=self.env|{'GOOS':self.info['GOHOSTOS'],'GOARCH':self.info['GOHOSTARCH']}
        built=self.execute([self.go,'build','-o',str(self.helper),str(HELPER)],self.cache,env=host)
        if built.returncode:raise KitBug('Pinned category helper failed to build')
        self.initial=self.provenance()

    def execute(self,args,directory,*,input=None,env=None):
        try:return subprocess.run(args,cwd=directory,env=env or self.env,input=input,capture_output=True,timeout=180)
        except (OSError,subprocess.TimeoutExpired) as e:raise KitBug('Go oracle operational failure: '+type(e).__name__) from e

    def provenance(self):
        compiler=self.goroot/'pkg/tool'/f'{self.info["GOHOSTOS"]}_{self.info["GOHOSTARCH"]}'/'compile'
        return {'version':self.info['GOVERSION'],'go_sha256':digest(Path(self.go).resolve()),
                'compiler_sha256':digest(compiler),'codes_sha256':digest(self.codes_path),
                'helper_source_sha256':digest(HELPER),'helper_binary_sha256':digest(self.helper),
                'target':TARGET,'environment':{k:v for k,v in self.env.items() if k.startswith(('GO','CGO'))},
                'build':['go','build','-gcflags=-e','./...'],
                'dependencies':'none; dependency-free generated modules; downloads disabled',
                'vet':'not run; separate non-label channel'}

    def check(self,files,directory):
        directory=Path(directory).resolve();directory.mkdir(parents=True)
        if files.get('go.mod')!=f'module {MODULE}\n\ngo 1.27.1\n'.encode():raise KitBug('Unexpected generated module identity')
        if any(p.endswith('_test.go') or not (p=='go.mod' or p.endswith('.go')) for p in files):raise KitBug('Non-production generated source')
        write_files(directory,files)
        before={p:digest(directory/p) for p in files}
        built=self.execute([self.go,'build','-gcflags=-e','./...'],directory)
        if built.returncode not in (0,1):raise KitBug('Go build operational failure')
        listed=self.execute([self.go,'list','-e','-deps','-export','-json','./...'],directory)
        try:packages=json_stream(listed.stdout.decode())
        except (ValueError,UnicodeError) as e:raise KitBug('Invalid Go package listing') from e
        if listed.returncode not in (0,1) or not packages:raise KitBug('Incomplete Go package listing')
        analyzed=sorted((Path(p['Dir'])/f).relative_to(directory).as_posix() for p in packages if p.get('Dir') and Path(p['Dir']).is_relative_to(directory) for f in p.get('GoFiles',[]))
        if analyzed!=sorted(p for p in files if p.endswith('.go')):raise KitBug('Oracle did not cover all production sources')
        checked=self.execute([str(self.helper),str(directory)],directory,input=listed.stdout)
        if checked.returncode:raise KitBug('Go category helper failed')
        try:diagnostics=json.loads(checked.stdout)
        except ValueError as e:raise KitBug('Invalid Go category diagnostics') from e
        positions=compiler_positions((built.stdout+b'\n'+built.stderr).decode('utf-8','replace'))
        for d in diagnostics:
            d['category']=self.names.get(d['code'],'UnknownCode')
            d['compiler_position_match']=any(same_site(d,p) for p in positions)
            c=d['category']
            if c=='UndeclaredImportedName':rule='GO-1'
            elif c=='WrongArgCount':rule='GO-3'
            elif c in DUPLICATES:rule='GO-4' # Imports included (frozen clarification).
            elif c=='BrokenImport' and d.get('import_path','').startswith(MODULE+'/') and not any(p.startswith(d['import_path'][len(MODULE)+1:]+'/') for p in files):rule='GO-2'
            else:rule=None
            d['contract']=rule
        locations={}
        for path,content in files.items():
            lines=content.decode().splitlines()
            for n,line in enumerate(lines[:-1]):
                marker=re.fullmatch(r'// declaration ([A-Za-z_0-9]+) ([A-Za-z_0-9]+) ([A-Za-z_0-9]+)',line)
                if marker:
                    identity,name,kind=marker.groups()
                    token=re.search(r'\b'+re.escape(name)+r'\b',lines[n+1])
                    if token:locations[identity]={'path':path,'line':n+2,'column':token.start()+1,'name':name,'kind':kind}
        matched=[d for d in diagnostics if d['compiler_position_match']]
        if built.returncode and (not positions or not matched):raise KitBug('Unclassified Go build failure')
        if any(not any(same_site(d,p) for d in matched) for p in positions):raise KitBug('Unmatched compiler error position')
        if built.returncode==0 and diagnostics:raise KitBug('Build/category-helper disagreement')
        if before!={p:digest(directory/p) for p in files} or set(files)!={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}:raise KitBug('Oracle mutated generated sources/module files')
        if self.provenance()!=self.initial:raise KitBug('Go toolchain/helper changed')
        return {'verdict':'broken' if built.returncode else 'valid','exit':built.returncode,
                'files_analyzed':len(analyzed),'declaration_locations':locations,'diagnostics':diagnostics,'compiler_positions':positions,
                'stdout':built.stdout.decode('utf-8','replace'),'stderr':built.stderr.decode('utf-8','replace')}


def validate(template,case,observations,rendered):
    contract=rendered['contract']['id'];expected_bad=set(case['oracle']['broken_states'])
    from itertools import combinations
    branches=[b['id'] for b in case['branches']]
    required={'+'.join(s) or 'target' for size in range(len(branches)+1) for s in combinations(branches,size)}
    if set(observations)!=required or not expected_bad<=required:raise KitBug('Missing declared Go oracle states')
    if any(s=='target' or '+' not in s for s in expected_bad):raise KitBug('Go target and all tips must build')
    for state,result in observations.items():
        expected='broken' if state in expected_bad else 'valid'
        if result['verdict']!=expected:raise KitBug('Oracle/template disagreement at '+state)
        errors=[d for d in result['diagnostics'] if d['compiler_position_match']]
        roots=[d for d in errors if d['contract']==contract]
        if expected=='broken' and not roots:raise KitBug('Wrong Go compiler category')
        for d in errors:
            if contract=='GO-4':
                declarations=[e for b in case['branches'] for e in b['edits'] if e['op']=='add_declaration']
                pair=case['oracle']['declaration_pair']
                locations=result.get('declaration_locations',{})
                if not all(identity in locations for identity in pair):raise KitBug('Missing declaration-pair locations')
                at=[locations[i] for i in pair if all(d[k]==locations[i][k] for k in ('path','line','column'))]
                secondary=(d['category'] in case['oracle'].get('secondary_categories',[]) and d.get('syntax')=='import'
                           and at and at[0]['kind']=='import' and d.get('import_path') in {MODULE+'/'+e['from_module'] for e in declarations if e['kind']=='import'})
                if not at or not (d['contract']==contract or secondary):raise KitBug('Unrelated Go declaration diagnostic')
            else:
                site=rendered['sites'][case['oracle']['site']]
                if d['contract']!=contract or d['path']!=site['path'] or not site['start_line']<=d['line']<=site['end_line']:raise KitBug('Unrelated Go use-site diagnostic')
                if d.get('import_path') and d['import_path']!=site['module']:raise KitBug('Wrong first-party package identity')
    labels=[b['id'] for b in case['branches']]
    pair_broken=any(len(s.split('+'))==2 and o['verdict']=='broken' for s,o in observations.items() if s!='target')
    full_broken=observations['+'.join(labels)]['verdict']=='broken'
    derived={'pairwise':'broken' if pair_broken else 'valid','combined':'broken' if full_broken else 'valid','plan':'broken' if full_broken else 'valid'}
    if derived!={m:e['verdict'] for m,e in case['expected'].items()}:raise KitBug('Go per-mode template/oracle disagreement')
    return derived

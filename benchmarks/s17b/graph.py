"""Local immutable Git graph proofs. No clone, fetch, checkout or external API."""
from dataclasses import dataclass
import hashlib
import re
import subprocess

from conformance.git import environment


class Unresolved(ValueError):pass
SHA=re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')


@dataclass(frozen=True)
class Anchor:
    method:str
    C:str|None=None
    D:str|None=None
    n:int=0
    proof:str|None=None
    reason:str|None=None
    source_base:str|None=None


class Graph:
    def __init__(self,repo,runner=subprocess.run):self.repo=repo;self.runner=runner
    def git(self,*args,input=None,check=True):
        try:result=self.runner(['git',*args],cwd=self.repo,env=environment(),input=input,capture_output=True,timeout=60)
        except (OSError,subprocess.TimeoutExpired) as error:raise Unresolved('missing-or-invalid-git-evidence') from error
        if check and result.returncode:raise Unresolved('missing-or-invalid-git-evidence')
        return result
    def text(self,*args):
        try:return self.git(*args).stdout.decode().strip()
        except UnicodeError as error:raise Unresolved('unreadable-git-evidence') from error
    def commit(self,sha):
        if not isinstance(sha,str) or not SHA.fullmatch(sha):raise Unresolved('invalid-object-id')
        return self.text('rev-parse','--verify',sha+'^{commit}')
    def parents(self,sha):return self.text('show','-s','--format=%P',self.commit(sha)).split()
    def ancestor(self,a,b):
        code=self.git('merge-base','--is-ancestor',self.commit(a),self.commit(b),check=False).returncode
        if code not in (0,1):raise Unresolved('ancestor-unavailable')
        return code==0
    def chain(self,head,n=None):
        args=['rev-list','--first-parent']
        if n is not None:args += ['--max-count='+str(n)]
        return self.text(*args,self.commit(head)).splitlines()
    def merge_bases(self,a,b):return self.text('merge-base','--all',self.commit(a),self.commit(b)).splitlines()
    def metadata(self,sha):
        return tuple(self.text('show','-s','--format=%an%x00%ae%x00%aI%x00%s',self.commit(sha)).split('\0'))
    def patch_id(self,sha):
        parents=self.parents(sha)
        if len(parents)!=1:raise Unresolved('merge-or-root-patch')
        data=self.git('diff','--no-ext-diff','--no-textconv','--binary',parents[0],sha).stdout
        if not data.strip():raise Unresolved('empty-patch')
        value=self.git('patch-id','--stable',input=data).stdout.decode().split()
        if not value:raise Unresolved('patch-id-unavailable')
        return value[0]
    def range(self,base,head):return self.text('rev-list','--reverse',self.commit(base)+'..'+self.commit(head)).splitlines()
    def patch_set(self,base,head):
        commits=self.range(base,head)
        if not commits:raise Unresolved('empty-pr-range')
        return {self.patch_id(c) for c in commits}
    def changed_paths(self,before,after):
        fields=self.git('diff','--name-status','--find-renames','-z',self.commit(before),self.commit(after)).stdout.split(b'\0')
        result=set();i=0
        while i<len(fields) and fields[i]:
            status=fields[i].decode();i+=1
            count=2 if status.startswith(('R','C')) else 1
            for _ in range(count):result.add(fields[i].decode());i+=1
        return result
    def bind(self,name,sha):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('unsafe evidence ref')
        self.git('update-ref','refs/s17b/'+name,self.commit(sha))


def anchor(graph,pr,default_head,pr_commits):
    C=pr.get('merge_commit_sha');n=pr.get('commits')
    unresolved=lambda reason:Anchor('unresolved',C=C,n=n if type(n) is int else 0,reason=reason)
    try:
        if not pr.get('merged_at') or pr.get('state')!='closed':return unresolved('default-anchor-unresolved')
        C=graph.commit(C);default_head=graph.commit(default_head)
        if C not in graph.chain(default_head):return unresolved('default-anchor-unresolved')
        if type(n) is not int or n<1 or len(pr_commits)!=n or len(set(pr_commits))!=n:return unresolved('commit-list-incomplete')
        # PR API sequence is oldest-first. Default first-parent sequence is
        # newest-first and is explicitly reversed below. Never reverse the PR
        # sequence merely to obtain a favorable match.
        commits=[graph.commit(c) for c in pr_commits];head=graph.commit(pr['head']['sha'])
        if commits[-1]!=head:return unresolved('commit-order-mismatch')
        def range_base(D):
            bases=graph.merge_bases(head,D)
            if len(bases)!=1 or set(graph.range(bases[0],head))!=set(commits):raise Unresolved('commit-range-mismatch')
            return bases[0]
        def proven(method,D,proof):
            base=range_base(D)
            return Anchor(method,C,D,n,proof,source_base=base)
        parents=graph.parents(C)
        if len(parents)==2:
            if parents[1]!=head:return unresolved('merge-parent-head-mismatch')
            return proven('merge',parents[0],'true-merge-parent')
        if len(parents)!=1:return unresolved('default-anchor-unresolved')
        if n==1:return proven('squash-n1',parents[0],'method-neutral-single-commit')
        candidates=list(reversed(graph.chain(C,n)))
        if len(candidates)!=n:return unresolved('anchor-range-incomplete')
        pr_nonmerge=[c for c in commits if len(graph.parents(c))==1]
        end_nonmerge=[c for c in candidates if len(graph.parents(c))==1]
        meta=[graph.metadata(c) for c in commits];end_meta=[graph.metadata(c) for c in candidates]
        linear=len(pr_nonmerge)==n and len(end_nonmerge)==n
        if linear and meta==end_meta:
            return proven('rebase-proven',graph.parents(candidates[0])[0],'author-date-subject')
        try:
            pids=[graph.patch_id(c) for c in pr_nonmerge]
            end_pids=[graph.patch_id(c) if graph.changed_paths(graph.parents(c)[0],c) else None for c in end_nonmerge]
        except Unresolved:return unresolved('patch-proof-unavailable')
        if linear and pids==end_pids:
            return proven('rebase-proven',graph.parents(candidates[0])[0],'stable-patch-sequence')
        if set(meta)&set(end_meta) or set(pids)&set(end_pids):return unresolved('partial-anchor-match')
        # Merge commits have no patch-id/cherry line, but every tuple above is
        # still checked. Squash proof covers exactly the non-merge commit set.
        base=range_base(parents[0])
        parsed=[line.split() for line in graph.text('cherry',C,head,base).splitlines()]
        if len(parsed)!=len(pr_nonmerge) or any(len(x)!=2 or x[0]!='+' for x in parsed) or {x[1] for x in parsed}!=set(pr_nonmerge):
            return unresolved('squash-cherry-inconclusive')
        files=pr.get('_files')
        if not isinstance(files,list) or not pr.get('_files_complete'):return unresolved('squash-files-incomplete')
        wanted={f[k] for f in files for k in ('filename','previous_filename') if isinstance(f.get(k),str)}
        if graph.changed_paths(parents[0],C)!=wanted:return unresolved('squash-path-mismatch')
        return proven('squash-proven',parents[0],'negative-matches-nonmerge-cherry-and-paths')
    except (Unresolved,KeyError,TypeError):return unresolved('default-anchor-unresolved')


def own_bases(graph,D,head_a,head_b):
    bases=[]
    for head in (head_a,head_b):
        found=graph.merge_bases(head,D)
        if len(found)!=1 or found[0]==head:raise Unresolved('own-base-ambiguous-or-contained')
        bases.append(found[0])
    a,b=bases
    if graph.ancestor(a,b):later=b
    elif graph.ancestor(b,a):later=a
    else:raise Unresolved('incomparable-bases')
    return {'A':a,'B':b,'L':later}


def contamination(graph,head_a,head_b,D,C,earlier,bases):
    """B2 executes before integration, without checker or message evidence."""
    heads={'A':head_a,'B':head_b};other='B' if earlier=='A' else 'A'
    try:
        if graph.ancestor(C,heads[other]) or graph.ancestor(heads[earlier],heads[other]):return {'reason':'contaminated-heads','test':'integrated-earlier-pr'}
        if graph.ancestor(head_a,head_b) or graph.ancestor(head_b,head_a):return {'reason':'contaminated-heads','test':'ancestral-heads'}
        shared=graph.merge_bases(head_a,head_b)
        if len(shared)!=1 or not graph.ancestor(shared[0],D):return {'reason':'contaminated-heads','test':'shared-pr-only-history'}
        left=graph.patch_set(bases['A'],head_a);right=graph.patch_set(bases['B'],head_b)
        overlap=left&right
        if overlap:return {'reason':'contaminated-heads','test':'patch-intersection','patch_ids':sorted(overlap)}
        return {'reason':None,'test':'all-three-pass','shared_base':shared[0],'patch_counts':[len(left),len(right)]}
    except Unresolved:return {'reason':'contamination-proof-unavailable','test':'unresolved'}


def native_merge(graph,left,right):
    merged=graph.git('merge-tree','--write-tree',graph.commit(left),graph.commit(right),check=False)
    if merged.returncode==1:raise Unresolved('textual-conflict')
    if merged.returncode:raise Unresolved('merge-tree-operational-failure')
    tree=merged.stdout.decode().splitlines()[0]
    return graph.git('-c','commit.gpgSign=false','commit-tree',tree,'-p',left,'-p',right,input=b'S17b virtual integration\n').stdout.decode().strip()


def integrate_pair(graph,L,head_a,head_b,name):
    # This function is called only after the anchor/base/contamination ledger.
    A=native_merge(graph,L,head_a);B=native_merge(graph,L,head_b)
    if graph.merge_bases(A,B)!=[L]:raise Unresolved('normalized-base-ambiguous')
    AB=native_merge(graph,A,B);BA=native_merge(graph,B,A)
    if graph.text('rev-parse',AB+'^{tree}')!=graph.text('rev-parse',BA+'^{tree}'):
        raise Unresolved('integration-order-ambiguous')
    states={'L':L,'A_L':A,'B_L':B,'I_AB':AB,'I_BA':BA}
    for label,sha in states.items():graph.bind(name+'-'+label,sha)
    return states

"""Local synthetic DAG proofs; never clone/fetch or inspect public PR objects."""
from dataclasses import asdict

import pytest

from benchmarks.s17b.graph import Graph,anchor,own_bases,contamination,integrate_pair,Unresolved


def setup(repo,n=3):
    for i in range(4):repo.write('padding.txt',str(i));repo.commit('default padding '+str(i))
    repo.write('a.txt','base\n');repo.write('b.txt','base\n');D=repo.commit('source base')
    repo.branch('A',D);repo.checkout('A');commits=[]
    for i in range(n):
        repo.write('a.txt',f'change {i}\n');commits.append(repo.commit('PR item '+str(i)))
    H=commits[-1];repo.checkout('main')
    return Graph(repo.path),D,H,commits


def detail(H,C,n,merged=True):
    return {'state':'closed','merged_at':'2025-01-01T00:00:00Z' if merged else None,
            'merge_commit_sha':C,'head':{'sha':H},'commits':n, '_files_complete':True,'_files':[{'filename':'a.txt'}]}


def test_true_merge_parent_and_off_chain_rejection(repo):
    g,D,H,commits=setup(repo)
    repo.git('merge','--no-ff','--no-edit','A');C=repo.git('rev-parse','HEAD').stdout.decode().strip()
    result=anchor(g,detail(H,C,3),C,commits,D)
    assert result.method=='merge' and result.D==D
    assert anchor(g,detail(H,C,3),D,commits,D).method=='unresolved'
    assert anchor(g,detail(H,C,3,False),C,commits,D).method=='unresolved'


@pytest.mark.parametrize('mode',['squash','rebase'])
def test_single_commit_anchor_needs_no_merge_method(repo,mode):
    g,D,H,commits=setup(repo,1)
    repo.write('default-only','drift');repo.commit('drift')
    if mode=='squash':repo.git('merge','--squash','A');C=repo.commit('combined')
    else:repo.git('cherry-pick',H);C=repo.git('rev-parse','HEAD').stdout.decode().strip()
    result=anchor(g,detail(H,C,1),C,commits,D)
    assert result.method=='squash-n1' and result.D==g.parents(C)[0]


def test_three_commit_squash_negative_match_and_all_plus(repo):
    g,D,H,commits=setup(repo)
    repo.git('merge','--squash','A');C=repo.commit('unconventional arbitrary subject')
    result=anchor(g,detail(H,C,3),C,commits,D)
    assert (result.method,result.D)==('squash-proven',D)


@pytest.mark.parametrize('proof',['metadata','patch-id','conflict-resolved-metadata'])
def test_three_commit_rebase_proof_and_pre_range_anchor(repo,proof):
    g,D,H,commits=setup(repo)
    repo.write('default-only','drift');later=repo.commit('drift')
    if proof=='patch-id':
        for i,c in enumerate(commits):
            parent=g.parents(c)[0];diff=g.git('diff',parent,c).stdout
            # Apply the actual patch; subjects change, so only patch IDs prove it.
            import subprocess
            subprocess.run(['git','apply','--index','-'],cwd=repo.path,env=repo.env,input=diff,check=True)
            repo.commit('different subject '+str(i))
    else:
        for i,c in enumerate(commits):
            repo.git('cherry-pick',c)
            if proof=='conflict-resolved-metadata' and i==2:
                repo.write('a.txt','resolved differently\n');repo.git('add','a.txt');repo.git('commit','--amend','--no-edit')
    C=repo.git('rev-parse','HEAD').stdout.decode().strip()
    result=anchor(g,detail(H,C,3),C,commits,D)
    assert result.method=='rebase-proven' and result.D==later
    assert result.proof==('stable-patch-sequence' if proof=='patch-id' else 'author-date-subject')


def test_partial_match_and_copied_subject_never_false_rebase(repo):
    g,D,H,commits=setup(repo)
    repo.git('merge','--squash','A');C=repo.commit('PR item 0')
    assert anchor(g,detail(H,C,3),C,commits,D).method=='unresolved'
    assert anchor(g,detail(H,C,3),C,commits[:2],D).reason=='commit-list-incomplete'


def independent(repo):
    g,D,A,commits=setup(repo,1)
    repo.branch('B',D);repo.checkout('B');repo.write('b.txt','change 0\n');B=repo.commit('other PR')
    repo.checkout('main');repo.git('merge','--no-ff','--no-edit','A');C=g.text('rev-parse','HEAD')
    return g,D,A,B,C


def test_unrelated_equal_looking_edits_with_different_patch_ids_pass(repo):
    g,D,A,B,C=independent(repo)
    bases=own_bases(g,D,A,B)
    assert g.patch_set(D,A).isdisjoint(g.patch_set(D,B))
    assert contamination(g,A,B,D,C,'A',bases)['reason'] is None
    states=integrate_pair(g,D,A,B,'synthetic')
    assert g.text('rev-parse',states['I_AB']+'^{tree}')==g.text('rev-parse',states['I_BA']+'^{tree}')
    for label,sha in states.items():assert g.text('rev-parse','refs/s17b/synthetic-'+label)==sha


def test_later_head_containing_earlier_integration_is_contaminated(repo):
    g,D,A,B,C=independent(repo)
    repo.checkout('B');repo.git('merge','--no-ff','--no-edit','main');updated=g.text('rev-parse','HEAD')
    assert contamination(g,A,updated,D,C,'A',own_bases(g,D,A,updated))['test']=='integrated-earlier-pr'


def test_shared_pr_only_prefix_is_contaminated(repo):
    g,D,A,commits=setup(repo,1)
    repo.branch('private-prefix',D);repo.checkout('private-prefix');repo.write('common','private');X=repo.commit('private prefix')
    repo.branch('left',X);repo.checkout('left');repo.write('left','change');left=repo.commit('left')
    repo.branch('right',X);repo.checkout('right');repo.write('right','change');right=repo.commit('right')
    assert contamination(g,left,right,D,A,'A',{'A':D,'B':D})['test']=='shared-pr-only-history'


def test_cherry_picked_content_is_contaminated_without_ancestry(repo):
    g,D,A,B,C=independent(repo)
    repo.checkout('B');repo.git('cherry-pick',A);copy=g.text('rev-parse','HEAD')
    assert not g.ancestor(A,copy)
    assert contamination(g,A,copy,D,C,'A',own_bases(g,D,A,copy))['test']=='patch-intersection'


def test_empty_and_merge_patches_are_not_empty_independence_proofs(repo):
    g,D,A,B,C=independent(repo)
    with pytest.raises(Unresolved):g.patch_id(C)
    repo.checkout('B');empty=repo.commit('empty')
    with pytest.raises(Unresolved):g.patch_id(empty)


def test_normalized_raw_shas_accepted_by_product_combined_mode(repo):
    g,D,A,B,C=independent(repo)
    states=integrate_pair(g,D,A,B,'raw-ref')
    from crosswire.combined import analyze_combined
    report=analyze_combined(repo.path,[states['A_L'],states['B_L']],D,cache=False)
    assert not report.findings


def test_missing_head_object_fails_closed(repo):
    g,D,H,commits=setup(repo)
    assert anchor(g,detail('f'*40,D,3),D,commits,D).method=='unresolved'


@pytest.mark.parametrize('mode',['incomparable','multiple','contained'])
def test_own_base_uncertainty_is_never_an_invented_common_base(mode):
    from types import SimpleNamespace
    def bases(head,D):
        if mode=='multiple':return ['one','two']
        if mode=='contained':return [head]
        return ['base-'+head]
    graph=SimpleNamespace(merge_bases=bases,ancestor=lambda a,b:False)
    with pytest.raises(Unresolved):own_bases(graph,'default','headA','headB')


def test_native_textual_conflict_remains_unlabelled(repo):
    g,D,A,commits=setup(repo,1)
    repo.branch('conflict',D);repo.checkout('conflict');repo.write('a.txt','other change\n');B=repo.commit('other')
    with pytest.raises(Unresolved,match='textual-conflict'):integrate_pair(g,D,A,B,'conflicted')


def test_reverse_tree_disagreement_is_checked_before_binding(monkeypatch):
    from types import SimpleNamespace
    from benchmarks.s17b import graph as module
    values=iter(['normA','normB','AB','BA'])
    monkeypatch.setattr(module,'native_merge',lambda *a:next(values))
    graph=SimpleNamespace(merge_bases=lambda *a:['L'],text=lambda *a:a[-1],bind=lambda *a:pytest.fail('No evidence refs for ambiguous trees'))
    with pytest.raises(Unresolved,match='integration-order-ambiguous'):integrate_pair(graph,'L','headA','headB','order')


@pytest.mark.parametrize('mode',['squash','rebase-drops-merge'])
def test_pr_containing_default_merge_uses_nonmerge_cherry_count(repo,mode):
    g,D,first,commits=setup(repo,1)
    repo.write('drift.txt','default drift\n');drift=repo.commit('default drift')
    repo.checkout('A');repo.git('merge','--no-ff','--no-edit','main');merged=g.text('rev-parse','HEAD')
    repo.write('a.txt','final PR value\n');last=repo.commit('PR final')
    pr_commits=[first,merged,last];repo.checkout('main')
    if mode=='squash':repo.git('merge','--squash','A');C=repo.commit('aggregate unrelated subject')
    else:
        repo.git('cherry-pick',first,last);C=g.text('rev-parse','HEAD')
    result=anchor(g,detail(last,C,3),C,pr_commits,D)
    assert result.method==('squash-proven' if mode=='squash' else 'unresolved')
    if mode=='squash':assert result.D==drift and result.source_base==drift


def test_reversed_pr_sequence_never_becomes_rebase_proof(repo):
    g,D,H,commits=setup(repo)
    repo.write('drift','main');repo.commit('drift');repo.git('cherry-pick',*commits);C=g.text('rev-parse','HEAD')
    assert anchor(g,detail(H,C,3),C,list(reversed(commits)),D).reason=='commit-order-mismatch'


def test_rewritten_rebase_tail_cannot_pass_squash_changed_path_check(repo):
    for n in range(4):repo.write('padding',str(n));repo.commit('padding '+str(n))
    repo.write('a.txt','base\n');repo.write('b.txt','base\n');D=repo.commit('base')
    repo.branch('A',D);repo.checkout('A');commits=[]
    for n,path in enumerate(['a.txt','b.txt','a.txt']):
        repo.write(path,'PR value '+str(n)+'\n');commits.append(repo.commit('original '+str(n)))
    H=commits[-1];repo.checkout('main')
    for n,path in enumerate(['a.txt','b.txt','a.txt']):repo.write(path,'rewritten '+str(n)+'\n');repo.commit('robot '+str(n))
    g=Graph(repo.path);C=g.text('rev-parse','HEAD');pr=detail(H,C,3)
    pr['_files']=[{'filename':'a.txt'},{'filename':'b.txt'}]
    assert anchor(g,pr,C,commits,D).reason=='squash-path-mismatch'


def test_changed_path_sets_include_both_rename_paths(repo):
    g,D,H,commits=setup(repo,1)
    repo.checkout('main');repo.rename('a.txt','renamed.txt');C=repo.commit('rename')
    assert g.changed_paths(D,C)=={'a.txt','renamed.txt'}

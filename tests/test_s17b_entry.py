"""Acquisition CLI wiring with fake subprocess/network adapters, never real APIs."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from benchmarks.s17b import entry,checkpoint
from benchmarks.s17b.__main__ import main
from benchmarks.s17b.acquire import FetchReceipt,fetch_head
from .test_s17b_selection import pr


def policy():
    return {'repositories':['one/repo','two/repo'],'maximum_git_bytes':30,'maximum_get_requests':1500,
            'per_repository_get_budget':187,'maximum_pairs':40,'pairs_per_repository':20,'pair_order_seed':'s17b-v1',
            'gh_version':'gh version synthetic','api_version':'2022-11-28','terminal_event_tolerance_seconds':60,
            'terminal_lower':'2022-01-01T00:00:00Z','collection_cutoff':'2026-11-18T00:00:00Z'}


def adapters(monkeypatch,root,*,budget_limit=30,fail_default=False):
    configured=policy();configured['maximum_git_bytes']=budget_limit;calls=[];transfers=[];budgets=[]
    monkeypatch.setattr(checkpoint.Permit,'verify',lambda self:deepcopy(configured))
    # Substitute only the round's checkpoint digest; no checkpoint/auth file is
    # manufactured. Real response-file hashes still use the actual helper.
    monkeypatch.setattr('benchmarks.s17b.acquire.sha',lambda path:checkpoint.sha(path) if path.exists() else 'f'*64)
    def runner(args,**kwargs):
        calls.append(args)
        if args==['gh','--version']:return SimpleNamespace(returncode=0,stdout='gh version synthetic\n',stderr='')
        if args[:2]==['gh','api']:
            assert args[2:4]==['--method','GET']
            endpoint=args[-1].split('?',1)[0];parts=endpoint.split('/')
            if len(parts)==3:body={'private':False,'id':1,'default_branch':'main'}
            elif parts[3]=='commits':body={'sha':'a'*40}
            elif len(parts)==4:body=[pr(1),pr(2)]
            else:
                n=int(parts[4]);value=pr(n)
                if parts[3]=='issues':body=value['_timeline']
                elif len(parts)==5:body={**value,'head':{'sha':str(n)*40},'commits':1}
                elif parts[5]=='files':body=value['_files']
                elif parts[5]=='commits':body=[{'sha':str(n)*40}]
                else:raise AssertionError(args)
            return SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\n\n'+json.dumps(body),stderr='')
        assert args[0]=='git'
        stdout=(args[-1].split('^')[0]+'\n').encode() if args[1:3]==['rev-parse','--verify'] else b''
        return SimpleNamespace(returncode=0,stdout=stdout,stderr=b'')
    def transport(args,**kwargs):
        assert (root/'metadata.json').exists() # selected cohort durable before Git
        transfers.append((args,kwargs))
        ref=args[-1]
        if ref.startswith('refs/heads/'):
            return FetchReceipt('a'*40,5,'synthetic default unavailable' if fail_default else None)
        return FetchReceipt(ref.split('/')[2]*40,3)
    def slots(selected,graph,default,metadata,permit,budget,transport,*,integrate):
        assert integrate is False;budgets.append(budget);rows=[]
        for slot in selected:
            for name in ('A','B'):
                n=slot[name];fetch_head(graph,n,slot['details'][name]['head']['sha'],permit,budget,transport)
                metadata.commits(n,slot['details'][name]['commits'])
            rows.append({k:slot[k] for k in ('A','B','slot','rank','hash')} |
                        {'status':'ready','anchor_method':'squash-n1','reason':None})
        return rows
    monkeypatch.setattr(entry,'prepare_slots',slots)
    return runner,transport,calls,transfers,budgets


def test_acquisition_cli_wires_metadata_clones_heads_and_one_shared_budget(tmp_path,monkeypatch):
    root=tmp_path/'round';runner,transport,calls,transfers,budgets=adapters(monkeypatch,root)
    # Neither file exists: Permit verification is faked, not an authorization
    # written by the tester or an operational checkpoint.
    cp=tmp_path/'checkpoint';auth=tmp_path/'authorization'
    assert main(['--acquire','--checkpoint',str(cp),'--authorization',str(auth),'--root',str(root)],runner=runner,transport=transport)==0
    result=json.loads((root/'acquisition.json').read_text())
    assert result['status']=='acquired' and result['git_bytes']==22 and len(transfers)==6
    assert len(budgets)==2 and budgets[0] is budgets[1] and budgets[0].used==22
    assert [row['default_fetch']['fetched_default_sha'] for row in result['repositories']]==['a'*40]*2
    assert result['get_requests']==22 and len(result['request_ledger'])==22
    assert all(r['summary']['anchor_method']=={'squash-n1':1} for r in result['repositories'])
    assert not cp.exists() and not auth.exists()
    assert len(list(root.glob('repository-*.json')))==2
    assert all(command[0] in {'gh','git'} for command in calls)
    before=len(calls)
    with pytest.raises(FileExistsError):main(['--acquire','--checkpoint',str(cp),'--authorization',str(auth),'--root',str(root)],runner=runner,transport=transport)
    assert len(calls)==before # no implicit second round or replay


def test_missing_authorization_stops_before_any_root_or_runner(tmp_path):
    checkpoint_file=tmp_path/'checkpoint';checkpoint_file.write_text('{}')
    root=tmp_path/'round'
    with pytest.raises(FileNotFoundError):main(['--acquire','--checkpoint',str(checkpoint_file),'--authorization',str(tmp_path/'absent'),'--root',str(root)],runner=lambda *a,**kw:pytest.fail('No runner before Permit'),transport=lambda *a,**kw:pytest.fail('No fetch before Permit'))
    assert not root.exists()


def test_default_fetch_failure_preserves_selected_slots_and_metadata(tmp_path,monkeypatch):
    root=tmp_path/'round';runner,transport,_,transfers,_=adapters(monkeypatch,root,fail_default=True)
    result=entry.acquire(checkpoint.Permit(tmp_path/'absent',tmp_path/'absent'),root,runner=runner,transport=transport)
    assert result['status']=='acquisition-incomplete' and result['git_bytes']==10 and len(transfers)==2
    assert all(row['slots'][0]['status']=='unattempted' and row['slots'][0]['slot']==1 for row in result['repositories'])
    assert (root/'metadata.json').exists() and (root/'acquisition.json').exists()


def test_entry_uses_injected_object_store_transport_by_default(tmp_path,monkeypatch):
    root=tmp_path/'round';runner,transport,_,transfers,_=adapters(monkeypatch,root)
    constructed=[]
    def factory(permit,runner):constructed.append(permit);return transport
    monkeypatch.setattr(entry,'ObjectStoreTransport',factory)
    result=entry.acquire(checkpoint.Permit(tmp_path/'absent',tmp_path/'absent'),root,runner=runner)
    assert len(constructed)==1 and len(transfers)==6 and result['git_bytes']==22


@pytest.mark.parametrize('arguments',[['--acquire'],['--acquire','--policy','policy'],['--write-checkpoint','checkpoint']])
def test_acquisition_cli_rejects_incomplete_or_mixed_modes(arguments):
    with pytest.raises(SystemExit) as error:main(arguments,runner=lambda *a,**kw:pytest.fail('No runner'))
    assert error.value.code==2


def test_shared_ceiling_stops_next_repository_fetch_without_replacement(tmp_path,monkeypatch):
    root=tmp_path/'round';runner,transport,_,transfers,_=adapters(monkeypatch,root,budget_limit=10)
    code=main(['--acquire','--checkpoint',str(tmp_path/'absent'),'--authorization',str(tmp_path/'absent'),'--root',str(root)],runner=runner,transport=transport)
    result=json.loads((root/'acquisition.json').read_text())
    assert code==1 and result['status']=='acquisition-incomplete'
    assert result['git_bytes']==11 and result['git_stopped'] and len(transfers)==3
    assert all(row['slots'][0]['status']=='unattempted' for row in result['repositories'])
    assert result['repositories'][1]['reason']=='acquisition-incomplete-at-ceiling'


def test_outside_temporary_root_refuses_before_api_or_creating_directory(monkeypatch):
    monkeypatch.setattr(checkpoint.Permit,'verify',lambda self:policy())
    from pathlib import Path
    root=Path.home()/'crosswire-invalid-acquisition-test'
    with pytest.raises(ValueError,match='temporary root'):
        entry.acquire(checkpoint.Permit(Path('absent'),Path('absent')),root,
                      runner=lambda *a,**kw:pytest.fail('No runner'),transport=lambda *a,**kw:pytest.fail('No fetch'))

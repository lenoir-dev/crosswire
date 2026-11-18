"""F1 non-rolling per-repository endpoint budgets; synthetic GETs only."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from benchmarks.s17b.acquire import GhGet
from benchmarks.s17b.selection import RepositoryCeiling
from benchmarks.s17b import entry,checkpoint
from .test_s17b_selection import pr
from .test_s17b_entry import adapters


class Permit:
    def verify(self):
        return {'repositories':['one/repo','two/repo'],'gh_version':'test','api_version':'2022-11-28',
                'maximum_get_requests':1500,'per_repository_get_budget':187,
                'per_repository_metadata_get_budget':127,'per_repository_commits_get_budget':60}


def client_at(tmp_path):
    calls=[]
    def runner(args,**kw):
        calls.append(args[-1])
        return SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\n\n[]',stderr='')
    return GhGet(Permit(),tmp_path,runner,version_reader=lambda:'test'),calls,runner


def test_metadata_127_exhaustion_keeps_commit_reserve_and_next_repository(tmp_path):
    client,calls,runner=client_at(tmp_path)
    for n in range(1,128):client.get(f'repos/one/repo/pulls/{n}')
    with pytest.raises(RepositoryCeiling,match='metadata'):client.get('repos/one/repo/pulls/128')
    client.get('repos/one/repo/pulls/1/commits',page=1)
    client.get('repos/two/repo/pulls')
    assert len(calls)==129
    # Claims restored from disk must still enforce the class, including query
    # pagination. A cached response is not another request.
    restarted=GhGet(Permit(),tmp_path,runner,version_reader=lambda:'test')
    restarted.get('repos/one/repo/pulls/1/commits',page=1)
    with pytest.raises(RepositoryCeiling,match='metadata'):restarted.get('repos/one/repo/pulls/129')
    restarted.get('repos/one/repo/pulls/1/commits',page=2)
    assert len(calls)==130 and restarted.calls==130


def test_commit_60_exhaustion_keeps_metadata_reserve_and_next_repository(tmp_path):
    client,calls,_=client_at(tmp_path)
    for page in range(1,61):client.get('repos/one/repo/pulls/1/commits',page=page)
    with pytest.raises(RepositoryCeiling,match='commits'):client.get('repos/one/repo/pulls/1/commits',page=61)
    client.get('repos/one/repo/pulls/1/files')
    client.get('repos/two/repo/pulls/1/commits')
    assert len(calls)==62
    # Unspent metadata allowance cannot be borrowed by the commit class.
    with pytest.raises(RepositoryCeiling,match='commits'):client.get('repos/one/repo/pulls/2/commits')
    assert len(calls)==62


def test_metadata_walk_ceiling_preserves_selected_slot_commit_lists(tmp_path,monkeypatch):
    root=tmp_path/'round'
    base_runner,transport,_,transfers,_=adapters(monkeypatch,root)
    policy=Permit().verify()
    policy.update(maximum_git_bytes=30,maximum_pairs=40,pairs_per_repository=20,pair_order_seed='s17b-v1',
                  terminal_lower='2022-01-01T00:00:00Z',collection_cutoff='2026-11-18T00:00:00Z',
                  terminal_event_tolerance_seconds=60,gh_version='gh version synthetic')
    monkeypatch.setattr(checkpoint.Permit,'verify',lambda self:deepcopy(policy))
    commit_requests=[]
    def runner(args,**kw):
        if args[:2]==['gh','api']:
            parts=args[-1].split('?',1)[0].split('/')
            if len(parts)==4 and parts[3]=='pulls':
                # First ranked pair passes. A later pair's unseen PR consumes
                # the remaining metadata allowance and stops the walk.
                body=[pr(n) for n in (1,2,3)]
                return SimpleNamespace(returncode=0,stdout='HTTP/2.0 200 OK\n\n'+json.dumps(body),stderr='')
            if len(parts)==6 and parts[3]=='issues' and parts[4]=='1':
                from urllib.parse import parse_qs,urlsplit
                page=int(parse_qs(urlsplit(args[-1]).query).get('page',['1'])[0])
                # A long, fully paginated unrelated timeline is metadata only;
                # reaching its next page cannot borrow the commit-list reserve.
                body=[{'event':'commented','created_at':'2025-01-01T00:00:00Z'}]*100
                endpoint='/'.join(parts)
                headers=f'HTTP/2.0 200 OK\nLink: <https://api.github.com/{endpoint}?page={page+1}>; rel="next"\n\n'
                return SimpleNamespace(returncode=0,stdout=headers+json.dumps(body),stderr='')
            if len(parts)==6 and parts[5]=='commits':commit_requests.append('/'.join(parts))
        return base_runner(args,**kw)
    result=entry.acquire(checkpoint.Permit(tmp_path/'absent',tmp_path/'absent'),root,runner=runner,transport=transport)
    metadata=json.loads((root/'metadata.json').read_text())
    assert all(r['selection']['stop_reason']=='repository-request-ceiling' for r in metadata['repositories'])
    assert all(len(r['selection']['selected'])==1 for r in metadata['repositories'])
    assert len(commit_requests)==4 and len(transfers)==6
    assert all(r['slots'][0]['status']=='ready' for r in result['repositories'])
    assert result['get_requests']==258 # 2 * (127 metadata + 2 commit-list GETs)
    assert result['status']=='acquisition-incomplete' # prefix remains incomplete, never hidden


@pytest.mark.parametrize('field,value',[
    ('per_repository_metadata_get_budget',126),('per_repository_commits_get_budget',61)])
def test_checkpoint_refuses_changed_sub_budget_protocol_fields(tmp_path,monkeypatch,field,value):
    from pathlib import Path
    policy=json.loads((checkpoint.ROOT/'benchmarks/s17b/policy.json').read_text())
    pinned_runtime={key:policy[key] for key in ('python_version','git_version')}
    monkeypatch.setattr(checkpoint,'runtime_pins',lambda:pinned_runtime)
    policy[field]=value
    with pytest.raises(ValueError,match='Policy protocol field changed: '+field):
        checkpoint.prepare(policy,tmp_path/'unwritten-checkpoint')
    assert not (tmp_path/'unwritten-checkpoint').exists()


@pytest.mark.parametrize('endpoint,phase',[
    ('repos/one/repo/pulls/1/commits','commits'),
    ('repos/one/repo/pulls/1/commits?page=2','commits'),
    ('repos/one/repo/commits/main','metadata'),
    ('repos/one/repo/issues/1/timeline','metadata'),
    ('repos/one/repo/pulls/1/files','metadata')])
def test_budget_class_is_exact_endpoint_never_query_or_message(endpoint,phase):
    from benchmarks.s17b.acquire import endpoint_class
    assert endpoint_class(endpoint)==phase

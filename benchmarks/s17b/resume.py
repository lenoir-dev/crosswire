"""Acquisition-only durable fetch receipts and single-controller root lock."""
from dataclasses import asdict,dataclass
import hashlib,json
from pathlib import Path

from .journal import write
from .selection import Ceiling
from .acquire import FetchReceipt


@dataclass(frozen=True)
class CachedFetchReceipt(FetchReceipt):
    replayed:bool=True


class FetchJournal:
    """Replay measured receipts; interrupted/unmeasurable transfers fail closed.

    Cached receipts contribute zero additional bytes; original bytes are restored
    once into the cohort budget. Unknown partial transfers are never re-fetched.
    """
    supports_resume=True
    def __init__(self,root,transport,budget,checkpoint,approved):
        from .acquire import FetchReceipt
        self.root=Path(root);self.directory=self.root/'fetches';self.directory.mkdir(exist_ok=True)
        self.transport=transport;self.budget=budget;self.checkpoint=checkpoint;self.approved=approved
        claims=sorted(self.directory.glob('*.started.json'),key=lambda path:json.loads(path.read_text())['request'])
        for claim in claims:
            request=json.loads(claim.read_text())
            if request['checkpoint_sha256'] not in approved:raise ValueError('Fetch journal checkpoint drift')
            result=claim.with_name(claim.name.replace('.started.json','.result.json'))
            if not result.exists():budget.stopped=True;raise Ceiling('Unmeasurable interrupted fetch; no refetch')
            value=json.loads(result.read_text())
            if value['checkpoint_sha256'] not in approved:raise ValueError('Fetch result checkpoint drift')
            budget.account(FetchReceipt(**value['receipt']))

    def __call__(self,args,*,cwd,maximum_bytes):
        from .acquire import FetchReceipt
        clone=Path(cwd).resolve().relative_to(self.root.resolve()).as_posix()
        key=hashlib.sha256(json.dumps([clone,args],separators=(',',':')).encode()).hexdigest()
        result=self.directory/(key+'.result.json');claim=self.directory/(key+'.started.json')
        if result.exists():
            saved=json.loads(result.read_text())
            if saved['checkpoint_sha256'] not in self.approved:raise ValueError('Fetch result checkpoint drift')
            receipt=saved['receipt'];return CachedFetchReceipt(receipt['commit'],0,receipt['error'])
        if claim.exists():self.budget.stopped=True;raise Ceiling('Unmeasurable interrupted fetch; no refetch')
        write(claim,{'clone':clone,'args':args,'checkpoint_sha256':self.checkpoint,'maximum_bytes':maximum_bytes,'request':len(list(self.directory.glob('*.started.json')))+1})
        try:receipt=self.transport(args,cwd=cwd,maximum_bytes=maximum_bytes)
        except Exception as error:
            receipt=FetchReceipt(None,None,type(error).__name__)
            write(result,{'checkpoint_sha256':self.checkpoint,'receipt':asdict(receipt),'exception_class':type(error).__name__})
            self.budget.stopped=True
            raise Ceiling('Unmeasurable fetch; acquisition incomplete at ceiling') from error
        write(result,{'checkpoint_sha256':self.checkpoint,'receipt':asdict(receipt)})
        return receipt

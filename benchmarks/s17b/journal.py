"""Durable acquisition records; no transport or semantic observation."""
import json
import os
from pathlib import Path
import tempfile


def write(path,value,*,replace=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    if replace:
        fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    else:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);temporary=None
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        if temporary:os.replace(temporary,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if temporary and os.path.exists(temporary):os.unlink(temporary)


def selection_policy(policy):
    return {**{key:value for key,value in policy.items() if key!='apparatus'},
            'apparatus':{key:value for key,value in policy.get('apparatus',{}).items() if key!='resume'}}

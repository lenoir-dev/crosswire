"""Focused runtime export smoke oracle; never imports the detector."""
import os
from pathlib import Path
import subprocess
import tempfile
from .corpus import export


def smoke(case, python):
    results={}
    with tempfile.TemporaryDirectory(prefix='crosswire-runtime-') as temporary:
        for label,sha in [('target',case['target']),*case['tips'].items(),('integrated',case['integrated'])]:
            root=Path(temporary)/label;export(Path(case['path']),sha,root)
            consumer=root/case['consumer']
            if not consumer.exists():
                results[label]={'status':'pass','reason':'no new consumer in this state'}
                continue
            command=[python,'-B',str(consumer)]
            try:
                r=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30,env=os.environ|{'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':os.pathsep.join([str(root),str(root/'src')])})
                results[label]={'status':'pass' if r.returncode==0 else 'fail','returncode':r.returncode,'stderr':r.stderr}
            except (OSError,subprocess.TimeoutExpired) as exc:
                results[label]={'status':'unlabelled','reason':type(exc).__name__}
    return results

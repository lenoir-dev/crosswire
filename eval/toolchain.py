"""Verify the pinned local interpreter, Node binary and checker before labelling."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def verify(python, checker):
    pins=json.loads(Path(__file__).with_name('toolchain.json').read_text())
    for key,path,args in [('python',python,['--version']),('node',shutil.which('node'),['--version']),('pyright',checker,['--version'])]:
        assert path, f'{key} missing'
        assert hashlib.sha256(Path(path).resolve().read_bytes()).hexdigest()==pins[key]['sha256'], f'{key} artifact mismatch'
        output=subprocess.check_output([path,*args],text=True,env=os.environ|{'PYRIGHT_PYTHON_FORCE_VERSION':'1.1.407','PYRIGHT_PYTHON_IGNORE_WARNINGS':'1'})
        assert pins[key]['version'] in output.splitlines(), f'{key} version mismatch'
    assert tree_digest(checker_bundle(python))==pins['pyright']['npm_tree_sha256'], 'Pyright npm engine/typeshed mismatch'


def tree_digest(directory):
    """Hash the actual npm checker engine plus its bundled typeshed files."""
    root=Path(directory);h=hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_file():
            h.update(path.relative_to(root).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    return h.hexdigest()


def checker_bundle(python):
    code='from pyright._utils import install_pyright; print(install_pyright([],quiet=True))'
    return Path(subprocess.check_output([python,'-c',code],text=True,env=os.environ|{'PYRIGHT_PYTHON_FORCE_VERSION':'1.1.407','PYRIGHT_PYTHON_IGNORE_WARNINGS':'1'}).strip())

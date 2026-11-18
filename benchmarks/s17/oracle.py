"""Pinned full-checker S17 oracle; no imports of sealed eval apparatus."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from conformance.git import environment, write_files
from .identity import identify_files
from .m3 import Observation


PIN="1.1.407"
CONFIG={"typeCheckingMode":"basic","pythonVersion":"3.14","pythonPlatform":"Darwin",
        "reportMissingImports":"error","reportAttributeAccessIssue":"error","reportCallIssue":"error"}


def checker_env():
    return environment()|{"PYRIGHT_PYTHON_FORCE_VERSION":PIN,"PYRIGHT_PYTHON_IGNORE_WARNINGS":"1"}


def observe(files,directory,python,*,known_modules,include):
    directory=Path(directory).resolve();directory.mkdir(parents=True)
    write_files(directory,{p:s.encode() for p,s in files.items()})
    config={**CONFIG,"include":include,"extraPaths":["src","lib","."]}
    config_path=directory/'.s17-pyright.json'
    config_path.write_text(json.dumps(config,sort_keys=True,indent=2)+'\n')
    command=[python,'-I','-m','pyright','--outputjson','--pythonpath',python,'--project',str(config_path)]
    try:
        executed=subprocess.run(command,cwd=directory,env=checker_env(),capture_output=True,timeout=60)
        data=json.loads(executed.stdout)
    except (OSError,ValueError,subprocess.TimeoutExpired) as error:
        return Observation((),environment_failure=True),{'status':'unlabelled','reason':type(error).__name__}
    raw=data.get('generalDiagnostics');summary=data.get('summary',{})
    if executed.returncode not in (0,1) or data.get('version')!=PIN or not isinstance(raw,list):
        return Observation((),environment_failure=True),{'status':'unlabelled','reason':'checker-version-or-output','exit':executed.returncode}
    errors=[d for d in raw if d.get('severity')=='error']
    if summary.get('errorCount')!=len(errors) or (executed.returncode==0)!=(len(errors)==0):
        return Observation((),complete=False),{'status':'unlabelled','reason':'incomplete-checker-output'}
    normalized=[]
    for error in errors:
        file=Path(error['file']).resolve()
        if not file.is_relative_to(directory):
            return Observation((),complete=False),{'status':'unlabelled','reason':'out-of-scope-diagnostic'}
        normalized.append({**error,'file':file.relative_to(directory).as_posix()})
    observation=identify_files(files,normalized,known_modules=known_modules,files_analyzed=summary.get('filesAnalyzed',0))
    return observation,{'status':'complete' if observation.complete and not observation.environment_failure and not observation.ambiguous else 'unlabelled',
        'exit':executed.returncode,'version':PIN,'summary':summary,'diagnostics':normalized,
        'identity_observation':asdict(observation),'stderr':executed.stderr.decode('utf-8','replace'),'config':config}

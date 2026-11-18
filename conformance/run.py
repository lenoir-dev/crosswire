"""Run S16 against an installed crosswire, with independently checked fixtures.

  uv run --group eval python -m conformance.run --output /tmp/crosswire-conformance

Never imports crosswire or its adapters; every product invocation is a subprocess
in an isolated fixture. Oracle disagreement exits 2 before that case is scored.
"""
import argparse
import hashlib
from itertools import combinations
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from . import git
from .oracle import KitBug, PIN, check, checker_provenance, validate
from .render.python import render


TEMPLATES = Path(__file__).with_name("templates")
MODES = ("pairwise", "combined", "plan")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def apparatus_hashes():
    return {p.relative_to(Path(__file__).parent).as_posix():digest(p) for p in sorted(Path(__file__).parent.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


def load_cases():
    result, identities = [], set()
    for path in sorted(TEMPLATES.glob("*.json")):
        template = json.loads(path.read_text())
        if template["version"] != 1:
            raise KitBug("Unsupported template version")
        for case in template["cases"]:
            if case["id"] in identities:
                raise KitBug("Duplicate case identity")
            identities.add(case["id"])
            labels = [b["id"] for b in case["branches"]]
            if len(labels)!=len(set(labels)) or not 2 <= len(labels) <= 3:
                raise KitBug("Templates require two or three uniquely identified branches")
            if set(case["expected"]) != set(MODES) or case["proof"] not in {"closed","open"}:
                raise KitBug("Every template must declare all modes and its proof scope")
            if any(e["verdict"] not in {"valid","broken","unknown"} for e in case["expected"].values()):
                raise KitBug("Unknown expected verdict")
            result.append((path,template,case))
    if not result:
        raise KitBug("No conformance cases")
    return result


def materialization(rendered):
    return {"language":rendered["language"], "contract":rendered["contract"],
            "base":{p:b.decode("utf-8") for p,b in rendered["base"].items()},
            "branches":[{**b,"files":{p:None if value is None else value.decode("utf-8") for p,value in b["files"].items()}} for b in rendered["branches"]],
            "sites":rendered["sites"]}


def portable(value, *roots):
    if isinstance(value,dict):return {k:portable(v,*roots) for k,v in value.items()}
    if isinstance(value,list):return [portable(v,*roots) for v in value]
    if isinstance(value,tuple):return [portable(v,*roots) for v in value]
    if isinstance(value,str):
        for path,token in roots:
            value=value.replace(str(path),token)
        value=value.replace(str(Path.home()),"${HOME}")
    return value


def write(path, value, *roots):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(portable(value,*roots),sort_keys=True,indent=2)+"\n")


def installed_provenance(python):
    script=("import importlib.metadata,json,pathlib,sys,crosswire; "
            "print(json.dumps({'version':importlib.metadata.version('crosswire'),"
            "'package':str(pathlib.Path(crosswire.__file__).resolve().parent),'python_version':sys.version}))")
    result=subprocess.run([python,"-I","-c",script],cwd=tempfile.gettempdir(),env=git.environment(),capture_output=True,timeout=30)
    if result.returncode:
        raise KitBug("Install crosswire in --detector-python's environment before running the kit")
    data=json.loads(result.stdout)
    package=Path(data.pop("package"))
    hashes={p.relative_to(package).as_posix():digest(p) for p in sorted(package.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}
    data.update(package_files_sha256=hashes,python_sha256=digest(Path(python).resolve()))
    return data


def verdict(mode, report):
    if mode=="plan":
        broken=bool(report["blocked"])
    else:
        broken=any(f["severity"]=="error" for f in report["findings"])
    if broken:return "broken"
    return "unknown" if report["coverage"] in {"partial","bounded"} else "valid"


def assert_detector(case, mode, report, code, sites, observations):
    expected=case["expected"][mode]
    actual=verdict(mode,report)
    if actual!=expected["verdict"]:
        raise AssertionError(f"{mode}: expected {expected['verdict']}, observed {actual}")
    findings=[f for b in report["blocked"] for f in b["findings"]] if mode=="plan" else report["findings"]
    if any(f["rule"]=="CW005" for f in findings) or (mode=="combined" and report["skipped"]):
        raise AssertionError("Textual conflict/skipped integration in a clean semantic fixture")
    if code != (1 if actual=="broken" else 0):
        raise AssertionError("CLI exit disagrees with declared mode verdict")
    if actual=="unknown":
        if findings or not any("open" in key for key in report.get("limitations",{})):
            raise AssertionError("Open namespace needs an explicit gap and zero findings")
    elif actual=="broken" or "resolved_by" in expected:
        site=sites[case["oracle"]["site"]]
        if not findings:
            raise AssertionError("Missing required diagnostic")
        for finding in findings:
            if finding["rule"] not in {"CW001","CW002","CW006"} or finding["path"]!=site["path"]:
                raise AssertionError("Finding names an unrelated rule/use file")
            wanted=site[case["oracle"]["identity"]]
            identity=finding.get("symbol")
            if case["oracle"]["identity"]=="module":
                # M2: derive the missing module from the emitted identity and
                # rendered baseline index; member spelling is not a PY-2 key.
                identity=max((m for m in site["known_modules"] if identity==m or isinstance(identity,str) and identity.startswith(m+".")),key=len,default=None)
            if identity != wanted:
                raise AssertionError("Finding names an unrelated symbol/module")
            if not site["start_line"] <= finding.get("line",0) <= site["end_line"]:
                raise AssertionError("Finding names a different use-site occurrence")
        if "rule" in expected and (len(findings)!=1 or findings[0]["rule"]!=expected["rule"]):
            raise AssertionError("Wrong rule or extra diagnostic")
        if "resolved_by" in expected and (findings[0].get("resolved_by")!=expected["resolved_by"] or findings[0]["severity"]!="warning"):
            raise AssertionError("Third-branch repair must retain the resolved warning/evidence")
        for key in ("owner","culprits"):
            if key in expected and findings[0].get("branch" if key=="owner" else key)!=expected[key]:
                raise AssertionError("Incorrect diagnostic owner or minimal culprit set")
        if "culprits" in expected and findings[0].get("culprits_exact") is not True:
            raise AssertionError("A small minimal-cause fixture requires exact culprit evidence")
    elif findings:
        raise AssertionError("Unexpected finding on a compatible control")
    if mode=="plan":
        placed=[]
        for step in report["steps"]:
            group=step["branches"]
            if set(group)&set(placed):raise AssertionError("Planner repeats a branch")
            placed.extend(group)
            ordered=[b["id"] for b in case["branches"] if b["id"] in placed]
            if observations["+".join(ordered)]["verdict"]!="valid":
                raise AssertionError("Planner accepts an oracle-failing prefix")
        labels={b["id"] for b in case["branches"]}
        blocked={b["branch"] for b in report["blocked"]}
        if set(placed)|blocked != labels or set(placed)&blocked:
            raise AssertionError("Planner omitted or duplicated branches")


def invoke_detector(python, args, cwd):
    return subprocess.run([python,"-I","-m","crosswire",*args],cwd=cwd,
                          env=git.environment(),capture_output=True,timeout=90)


def run_case(path, template, case, destination, detector_python, checker_python):
    destination.mkdir(parents=True)
    rendered=render(template,case)
    payload={"template_sha256":digest(path),"template":template["id"],"case":case,
             "rendered":materialization(rendered)}
    write(destination/"rendered.json",payload)
    with tempfile.TemporaryDirectory(prefix="crosswire-conformance-") as temporary:
        root=Path(temporary).resolve();repo=root/"repo"
        target,tips=git.build(repo,rendered)
        labels=[b["id"] for b in case["branches"]]
        observations={}
        # Persist each independent result BEFORE any detector invocation.
        for size in range(len(labels)+1):
            for subset in combinations(labels,size):
                state="+".join(subset) or "target"
                revision=git.integrate(repo,target,tips,subset)
                files=git.files_at(repo,revision)
                observation=check(files,root/"oracle"/state,checker_python)
                observation.update(commit=revision,source_sha256={p:hashlib.sha256(b).hexdigest() for p,b in files.items()})
                observations[state]=observation
                write(destination/"oracle.json",{"pin":PIN,"states":observations},(root,"${CASE}"))
        try:
            validate(case,observations,rendered["sites"])
        except KitBug as error:
            write(destination/"result.json",{"status":"kit-bug","reason":str(error)},(root,"${CASE}"))
            raise
        results={};failures=[]
        for mode in MODES:
            args=["plan" if mode=="plan" else "check","--repo",str(repo),"--target","main","--no-cache","--format","json"]
            if mode=="combined":args.append("--combined")
            before=git.snapshot(repo)
            try:
                executed=invoke_detector(detector_python,[*args,*labels],root)
            except (OSError,subprocess.TimeoutExpired) as error:
                results[mode]={"exit":None,"error":type(error).__name__}
                failures.append(f"{mode}: detector operational failure ({type(error).__name__})")
                write(destination/"detector.json",results,(root,"${CASE}"))
                if before!=git.snapshot(repo):failures.append(f"{mode}: detector modified protected repository state")
                continue
            result={"exit":executed.returncode,"stdout":executed.stdout.decode("utf-8","replace"),
                    "stderr":executed.stderr.decode("utf-8","replace")}
            results[mode]=result
            try:
                if before!=git.snapshot(repo):raise AssertionError("Detector modified protected repository state")
                if executed.returncode not in (0,1):raise AssertionError("Detector operational failure")
                report=json.loads(executed.stdout)
                assert_detector(case,mode,report,executed.returncode,rendered["sites"],observations)
            except (AssertionError,ValueError,KeyError,TypeError) as error:
                failures.append(f"{mode}: {error}")
            write(destination/"detector.json",results,(root,"${CASE}"))
        result={"id":case["id"],"status":"fail" if failures else "pass", "contract":rendered["contract"],
                "oracle_states":len(observations),"modes":len(results),"failures":failures}
        write(destination/"result.json",result,(root,"${CASE}"))
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--case",action="append",help="Explicit case ID; subset is reported as partial")
    parser.add_argument("--detector-python",default=sys.executable)
    parser.add_argument("--checker-python",default=sys.executable)
    args=parser.parse_args(argv)
    # Preserve the venv executable spelling: resolving its symlink would select
    # the base interpreter and lose the installed package environment.
    args.detector_python=str(Path(args.detector_python).absolute())
    args.checker_python=str(Path(args.checker_python).absolute())
    output=args.output.resolve()
    if output.exists():parser.error("Use a fresh output directory; conformance evidence is never overwritten")
    output.mkdir(parents=True)
    rows=[]
    try:
        selected=load_cases()
        if args.case:
            selected=[item for item in selected if item[2]["id"] in args.case]
            if {item[2]["id"] for item in selected}!=set(args.case):raise KitBug("Unknown requested case")
        checker=checker_provenance(args.checker_python)
        detector=installed_provenance(args.detector_python)
        apparatus=apparatus_hashes()
        write(output/"provenance.json",{"checker":checker,"detector":detector,"apparatus_sha256":apparatus})
        for path,template,case in selected:
            try:
                result=run_case(path,template,case,output/case["id"],args.detector_python,args.checker_python)
            except (KitBug,OSError,subprocess.SubprocessError,ValueError) as error:
                result={"id":case["id"],"status":"kit-bug","reason":str(error)}
            rows.append(result)
            print(json.dumps(result,sort_keys=True),flush=True)
        stable=installed_provenance(args.detector_python)==detector and checker_provenance(args.checker_python)==checker
        if not stable or apparatus_hashes()!=apparatus:raise KitBug("Installed detector/checker or kit apparatus changed during conformance")
        if any(r["status"]=="kit-bug" for r in rows):status="kit-bug";code=2
        elif any(r["status"]=="fail" for r in rows):status="fail";code=1
        else:status="partial" if args.case else "pass";code=0
        write(output/"summary.json",{"status":status,"source_stable":stable,"cases":rows,"case_count":len(rows),
              "oracle_states":sum(r.get("oracle_states",0) for r in rows),"mode_checks":sum(r.get("modes",0) for r in rows)})
        return code
    except (KitBug,OSError,subprocess.SubprocessError,ValueError) as error:
        write(output/"summary.json",{"status":"kit-bug","reason":str(error),"cases":rows})
        print("kit-bug: "+str(error),file=sys.stderr)
        return 2


if __name__=="__main__":raise SystemExit(main())

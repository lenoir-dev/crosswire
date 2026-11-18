"""S19a public Go merge census; network only through explicit mod-download setup.

Clones are supplied under --root. Repository refs never move; git merge-tree may
write unreferenced objects in these disposable clones. No detector is executed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
GO = Path("/opt/homebrew/bin/go")
REPOS = [("chi", "https://github.com/go-chi/chi", "HTTP routing"),
         ("pflag", "https://github.com/spf13/pflag", "CLI parsing"),
         ("uuid", "https://github.com/google/uuid", "identifiers"),
         ("bbolt", "https://github.com/etcd-io/bbolt", "embedded key/value storage")]
RULES = [f"GO-{i}" for i in range(1, 10)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, cwd, env=None, timeout=120):
    start = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        return {"exit": result.returncode, "stdout": result.stdout.decode("utf-8", "replace"),
                "stderr": result.stderr.decode("utf-8", "replace"), "seconds": time.monotonic()-start}
    except subprocess.TimeoutExpired as error:
        return {"exit": None, "stdout": (error.stdout or b"").decode("utf-8", "replace"),
                "stderr": (error.stderr or b"").decode("utf-8", "replace"),
                "seconds": time.monotonic()-start, "timeout": True}


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, env=os.environ | {"GIT_OPTIONAL_LOCKS": "0"})


def environment(root, online=False):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("GO", "CGO", "GIT_")):
            env.pop(key)
    env.update(PATH="/usr/bin:/bin:/opt/homebrew/bin", LC_ALL="C", LANG="C", TZ="UTC",
               GOENV="off", GOTOOLCHAIN="local", GOWORK="off", GOOS="darwin", GOARCH="arm64",
               CGO_ENABLED="0", GOFLAGS="-mod=readonly", GOCACHE=str(root / "gocache"),
               GOMODCACHE=str(root / "modules"), GOPATH=str(root / "gopath"),
               GOPROXY="https://proxy.golang.org" if online else "off",
               GOSUMDB="sum.golang.org" if online else "off", GONOPROXY="", GONOSUMDB="",
               GOPRIVATE="", GOVCS="*:off", GOTELEMETRY="off", GOMAXPROCS="2")
    return env


def portable(value, root, goroot):
    if isinstance(value, dict):
        return {k: portable(v, root, goroot) for k,v in value.items()}
    if isinstance(value, list):
        return [portable(v, root, goroot) for v in value]
    if isinstance(value, str):
        for prefix, token in ((str(root), "${CENSUS}"), (str(goroot), "${GOROOT}"), (str(Path.home()), "${HOME}")):
            value = value.replace(prefix, token)
    return value


def json_stream(text):
    decoder, position, result = json.JSONDecoder(), 0, []
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        value, position = decoder.raw_decode(text, position)
        result.append(value)
    return result


def code_names(goroot):
    text = (goroot / "src/internal/types/errors/code_string.go").read_text()
    return {int(number): name for name,number in re.findall(r'x\[([A-Za-z_][A-Za-z_0-9]*)\s*-\s*(-?\d+)\]', text)}


def category(diagnostic):
    code, syntax = diagnostic["category"], diagnostic.get("syntax")
    if code == "UndeclaredImportedName":
        return "GO-1"
    if code == "WrongArgCount":
        return "GO-3"
    if code in {"DuplicateDecl", "DuplicateMethod", "DuplicateFieldAndMethod"}:
        return "GO-7" if syntax == "import" else "GO-4"
    if code == "WrongAssignCount" and syntax == "multi-assignment-call":
        return "GO-6"
    if code == "UnusedImport":
        return "GO-7"
    if code == "UndeclaredName" and syntax == "bare-call":
        return "GO-9"
    return None


def import_cycles(packages):
    graph = {p["ImportPath"]: p.get("Imports", []) for p in packages}
    stack, onstack, index, low, result = [], set(), {}, {}, []
    def visit(node):
        index[node] = low[node] = len(index)
        stack.append(node); onstack.add(node)
        for target in graph.get(node, []):
            if target not in graph:
                continue
            if target not in index:
                visit(target); low[node] = min(low[node], low[target])
            elif target in onstack:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component = []
            while True:
                member = stack.pop(); onstack.remove(member); component.append(member)
                if member == node:break
            if len(component)>1 or node in graph.get(node, []):
                result.append(sorted(component))
    for node in graph:
        if node not in index:visit(node)
    return result


def compiler_positions(text):
    # Parse only location prefixes; messages never assign a semantic category.
    return [{"path": path.removeprefix("./"), "line": int(line), "column": int(column)}
            for path,line,column in re.findall(r"(?m)^(.+?\.go):(\d+):(\d+):", text)]


def same_site(diagnostic, position):
    if position["path"] != diagnostic["path"]:
        return False
    if (position["line"],position["column"]) == (diagnostic["line"],diagnostic["column"]):
        return True
    start=(diagnostic.get("start_line",0),diagnostic.get("start_column",0))
    end=(diagnostic.get("end_line",0),diagnostic.get("end_column",0))
    return start != (0,0) and start <= (position["line"],position["column"]) < end


def classify(directory, env, helper, names, build):
    listed = run([str(GO), "list", "-e", "-deps", "-export", "-json", "./..."], directory, env)
    try:
        packages = json_stream(listed["stdout"])
    except (ValueError, KeyError):
        return {"status": "unclassified", "reason": "invalid-package-json", "diagnostics": []}
    if not packages or listed.get("timeout"):
        return {"status": "unclassified", "reason": "incomplete-package-list", "diagnostics": []}
    checked = subprocess.run([str(helper), str(directory)], input=listed["stdout"].encode(),
                             capture_output=True, env=env, timeout=120)
    if checked.returncode:
        return {"status": "unclassified", "reason": "category-helper-failed", "diagnostics": [],
                "helper_stderr": checked.stderr.decode("utf-8", "replace")}
    diagnostics = json.loads(checked.stdout)
    positions = compiler_positions(build["stdout"] + "\n" + build["stderr"])
    for diagnostic in diagnostics:
        diagnostic["category"] = names.get(diagnostic["code"], "UnknownCode")
        diagnostic["candidate_rule"] = category(diagnostic)
        diagnostic["compiler_position_match"] = any(same_site(diagnostic,p) for p in positions)
    return {"status": "classified", "diagnostics": diagnostics,
            "compiler_positions": positions, "import_cycles": import_cycles(packages),
            "missing_packages": [{"import_path": p["ImportPath"], "import_stack": p.get("Error",{}).get("ImportStack",[])}
                                 for p in packages if not p.get("Dir") and p.get("Error")],
            "package_errors": [{"import_path": p["ImportPath"], "error": p["Error"]} for p in packages if p.get("Error")]}


def snapshot(repo, commit, destination):
    if destination.exists():shutil.rmtree(destination)
    destination.mkdir(parents=True)
    content = git(repo, "archive", commit)
    with tarfile.open(fileobj=io.BytesIO(content)) as stream:
        stream.extractall(destination, filter="data")


def build_state(repo, commit, root, helper, names, cache, download_cache):
    key = (repo.name, commit)
    if key in cache:return cache[key]
    directory = root / "states" / repo.name
    snapshot(repo, commit, directory)
    state = {"commit": commit, "tree": git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()}
    go_mod = directory / "go.mod"
    if not go_mod.is_file():
        state.update(status="unlabelled", exclusion="no-root-module", diagnostics=[])
        cache[key]=state;return state
    if go_mod.is_symlink() or any(p.is_symlink() for p in directory.rglob("*.go")):
        state.update(status="unlabelled", exclusion="source-symlink-context", diagnostics=[])
        cache[key]=state;return state
    state["go_mod_sha256"] = digest(go_mod)
    state["go_sum_sha256"] = digest(directory / "go.sum") if (directory / "go.sum").exists() else None
    state["nested_modules"] = sorted(p.parent.relative_to(directory).as_posix() for p in directory.rglob("go.mod") if p != go_mod)
    # Only setup may touch the network. Identical original go.mod/sum bytes are
    # restored after download, before every offline oracle execution.
    original = {p: p.read_bytes() if p.exists() else None for p in (go_mod,directory / "go.sum")}
    dep_key = (state["go_mod_sha256"], state["go_sum_sha256"])
    if dep_key not in download_cache:
        download_cache[dep_key] = run([str(GO), "mod", "download", "-json"], directory, environment(root, True), timeout=180)
    download = download_cache[dep_key]
    state["dependency_setup_exit"] = download["exit"]
    state["dependency_setup_sha256"] = hashlib.sha256(json.dumps(download,sort_keys=True).encode()).hexdigest()
    for p, content in original.items():
        if content is None:p.unlink(missing_ok=True)
        else:p.write_bytes(content)
    before = {p.name: digest(p) if p.exists() else None for p in original}
    build = run([str(GO), "build", "-gcflags=-e", "./..."], directory, environment(root))
    state["build"] = build
    state["module_files_unchanged"] = before == {p.name: digest(p) if p.exists() else None for p in original}
    if build["exit"] == 0:
        state.update(status="pass", diagnostics=[])
    elif build["exit"] is None:
        state.update(status="unlabelled", exclusion="build-timeout", diagnostics=[])
    else:
        details = classify(directory, environment(root), helper, names, build)
        state.update(details)
        # First-party missing packages/cycles remain compiler candidates; missing
        # external dependencies or an invalid context must never become negatives.
        module = re.search(r"(?m)^module\s+(\S+)", go_mod.read_text())
        module_path = module.group(1).strip('"') if module else ""
        external_missing = [p for p in details.get("missing_packages", []) if not module_path or not p["import_path"].startswith(module_path + "/")]
        matched = [d for d in details.get("diagnostics",[]) if d.get("compiler_position_match") and d["category"] != "BrokenImport"]
        if external_missing or (download["exit"] != 0 and not matched):
            state.update(status="unlabelled", exclusion="dependency-environment")
        elif matched or details.get("import_cycles") or any(p["import_path"].startswith(module_path + "/") for p in details.get("missing_packages",[])):
            state["status"]="fail"
        else:
            state.update(status="unlabelled", exclusion="unclassified-build-failure")
    state["diagnostics"] = state.get("diagnostics", [])
    cache[key]=state
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/tmp/deneb-s19a"))
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/validation/s19a-go-census.json")
    args=parser.parse_args();root=args.root.resolve();root.mkdir(parents=True,exist_ok=True)
    env=environment(root)
    goroot=Path(subprocess.check_output([str(GO),"env","GOROOT"],env=env).decode().strip())
    version=subprocess.check_output([str(GO),"version"],env=env).decode().strip()
    assert version=="go version go1.27.1 darwin/arm64",version
    helper=root/"category-helper"
    compiled=run([str(GO),"build","-o",str(helper),str(Path(__file__).with_name("s19a_categories.go"))],ROOT,env,timeout=180)
    assert compiled['exit']==0,compiled
    report={"protocol":"S19a first-parent two-parent merges; latest 80/repo before outcomes; offline build; green target and parents",
            "toolchain":{"version":version,"go_sha256":digest(GO.resolve()),
                         "compile_sha256":digest(goroot/"pkg/tool/darwin_arm64/compile"),
                         "types_codes_sha256":digest(goroot/"src/internal/types/errors/code_string.go"),
                         "helper_sha256":digest(helper),"helper_source_sha256":digest(Path(__file__).with_name("s19a_categories.go")),
                         "census_source_sha256":digest(__file__),
                         "environment":{k:v for k,v in env.items() if k.startswith(("GO","CGO"))},
                         "oracle":["go","build","-gcflags=-e","./..."],"vet":"not run; separate channel, not semantic label"},
            "selection":[],"cases":[],"states":[],"dependency_setups":[]}
    selections=[]
    for name,url,domain in REPOS:
        repo=root/name;head=git(repo,"rev-parse","HEAD").decode().strip()
        merges=[]
        for line in git(repo,"rev-list","--first-parent","--min-parents=2","--max-parents=2","--parents",head).decode().splitlines()[:args.limit]:
            commit,*parents=line.split();merges.append({"merge":commit,"parents":parents})
        selection={"repository":name,"url":url,"domain":domain,"head":head,"merges":merges}
        report['selection'].append(selection);selections.append((repo,selection))
    # Persist selection and pins BEFORE executing any repository build.
    args.output.parent.mkdir(parents=True,exist_ok=True)
    preregistration=args.output.with_name("s19a-go-selection.json")
    if preregistration.exists():raise ValueError("Selection already frozen; inspect existing run")
    preregistration.write_text(json.dumps(portable({"toolchain":report['toolchain'],"selection":report['selection']},root,goroot),indent=2)+'\n')
    names=code_names(goroot);cache={};downloads={};start=time.monotonic()
    for repo,selection in selections:
        for index,item in enumerate(selection['merges']):
            commit,parents=item['merge'],item['parents']
            case={"repository":repo.name,**item,"date":git(repo,"show","-s","--format=%cI",commit).decode().strip(),
                  "subject":git(repo,"show","-s","--format=%s",commit).decode().strip()}
            merge=run(["git","merge-tree","--write-tree",*parents],repo,timeout=60)
            if merge['exit']==1:
                case.update(status="textual-conflict",classification=[])
            elif merge['exit']!=0:
                case.update(status="unlabelled",exclusion="merge-tree-error",merge_tree=merge)
            else:
                tree=merge['stdout'].splitlines()[0]
                bases=git(repo,"merge-base","--all",*parents).decode().splitlines()
                case.update(native_tree=tree,recorded_tree=git(repo,"rev-parse",f"{commit}^{{tree}}").decode().strip(),merge_bases=bases)
                # A commit-tree points at exactly merge-tree's result; no ref moves.
                integrated=subprocess.check_output(["git","-c","user.name=S19a","-c","user.email=census@example.invalid",
                    "commit-tree",tree,"-p",parents[0],"-p",parents[1],"-m","S19a native integration"],cwd=repo,
                    env=os.environ|{"GIT_AUTHOR_DATE":"@0 +0000","GIT_COMMITTER_DATE":"@0 +0000"}).decode().strip()
                case['native_commit']=integrated
                states=[build_state(repo,p,root,helper,names,cache,downloads) for p in parents]
                merged=build_state(repo,integrated,root,helper,names,cache,downloads)
                case.update(parent_statuses=[s['status'] for s in states],merge_status=merged['status'])
                case['recorded_status']=build_state(repo,commit,root,helper,names,cache,downloads)['status'] if tree!=case['recorded_tree'] else merged['status']
                case['recorded_tree_matches_native']=tree==case['recorded_tree']
                if any(s['status']!='pass' for s in states):
                    case.update(status="unlabelled",exclusion="non-green-parent")
                elif merged['status']=='unlabelled':
                    case.update(status="unlabelled",exclusion=merged.get('exclusion','merge-ineligible'))
                elif len(bases)!=1:
                    case.update(status="unlabelled",exclusion="multiple-merge-bases")
                else:
                    target=build_state(repo,bases[0],root,helper,names,cache,downloads)
                    case['target_status']=target['status']
                    if target['status']!='pass':case.update(status="unlabelled",exclusion="non-green-target")
                    elif merged['status']=='pass':case['status']='control'
                    else:
                        rules=Counter(d['candidate_rule'] for d in merged['diagnostics'] if d.get('compiler_position_match') and d.get('candidate_rule'))
                        if merged.get('import_cycles'):rules['GO-8']+=len(merged['import_cycles'])
                        if merged.get('missing_packages'):rules['GO-2']+=len(merged['missing_packages'])
                        case.update(status="positive-candidate",classification=dict(rules))
                        # Natural evidence, never substitute mutations when empty.
                        case['interaction_diff']=git(repo,"diff","--stat",bases[0],tree).decode()
                        later=git(repo,"rev-list","--first-parent","--reverse",f"{commit}..{selection['head']}").decode().splitlines()[:5]
                        case['followups']=[]
                        for followup in later:
                            s=build_state(repo,followup,root,helper,names,cache,downloads)
                            case['followups'].append({'commit':followup,'status':s['status'],
                                'subject':git(repo,'show','-s','--format=%s',followup).decode().strip(),
                                'diffstat':git(repo,'diff','--stat',f'{followup}^',followup).decode()})
            report['cases'].append(case)
            if (index+1)%10==0:print(json.dumps({'repository':repo.name,'completed':index+1,'selected':len(selection['merges']),'statuses':dict(Counter(c['status'] for c in report['cases'] if c['repository']==repo.name))}),flush=True)
            report['states']=[{'repository':r,**state} for (r,_),state in cache.items()]
            report['seconds']=time.monotonic()-start
            report['dependency_setups']=[{'go_mod_sha256':k[0],'go_sum_sha256':k[1],**v} for k,v in downloads.items()]
            temporary=args.output.with_suffix('.tmp');temporary.write_text(json.dumps(portable(report,root,goroot),indent=2)+'\n');temporary.replace(args.output)
    # Hash every downloaded module archive/info/mod/sumdb record, not mutable build cache.
    report['dependency_snapshot']={p.relative_to(root/'modules').as_posix():digest(p) for p in sorted((root/'modules/cache/download').rglob('*')) if p.is_file() and not p.name.endswith('.lock')}
    report['summary']={name:dict(Counter(c['status'] for c in report['cases'] if c['repository']==name)) for name,_,_ in REPOS}
    counts=Counter()
    for case in report['cases']:
        if case['status']=='positive-candidate':counts.update(case['classification'])
    report['ranking']=[{'rule':rule,'observed_diagnostics':counts[rule],'status':'deferred' if rule=='GO-5' else 'observed' if counts[rule] else 'unobserved'} for rule in RULES]
    report['source_stable']=digest(__file__)==report['toolchain']['census_source_sha256']
    args.output.write_text(json.dumps(portable(report,root,goroot),indent=2)+'\n')
    print(json.dumps({'summary':report['summary'],'ranking':report['ranking'],'seconds':time.monotonic()-start}),flush=True)


if __name__=='__main__':main()

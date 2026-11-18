"""Python syntax only; verdicts and branch topology belong to neutral templates."""
from copy import deepcopy


GAP = "".join(f"# stable integration separator {number:02d}\n" for number in range(16))
CAPABILITIES = {"rename", "delete", "move_module", "add_parameter", "remove_definition",
                "remove_forward", "add_forward", "add_use", "open_namespace", "preserve_forward"}


def apply(base, edits):
    state = deepcopy(base)
    for edit in edits:
        op = edit["op"]
        if op not in CAPABILITIES:
            raise ValueError("Unsupported Python operation: " + op)
        module = state["modules"].get(edit.get("module"))
        if op == "add_use":
            if edit["site"] in state["uses"]:
                raise ValueError("Duplicate use-site identity")
            state["uses"][edit["site"]] = {k:v for k,v in edit.items() if k != "op"}
        elif op == "move_module":
            if edit["to"] in state["modules"]:
                raise ValueError("Move destination exists")
            state["modules"][edit["to"]] = state["modules"].pop(edit["module"])
        elif op in {"rename", "add_parameter"}:
            declaration = next(d for d in module["declarations"] if d["id"] == edit["symbol"])
            if op == "rename":
                declaration["name"] = edit["to"]
            else:
                declaration.setdefault("parameters", []).append({"name":edit["name"], "required":edit["required"]})
        elif op in {"delete", "remove_definition"}:
            module["declarations"] = [d for d in module["declarations"] if d["id"] != edit["symbol"]]
        elif op == "remove_forward":
            module["forward"] = None
        elif op == "preserve_forward":
            # A compatible branch edits the same forwarding slot without
            # removing the independent binding. No detector-driven rewrite.
            module["forward_comment"] = "# forwarding binding retained\n"
        elif op == "add_forward":
            module["forward"] = {"module":edit["from_module"], "symbol":edit["symbol"], "guarded":False}
        elif op == "open_namespace":
            module["declarations"] = []
            module["open"] = {"module":edit["from_module"], "mechanism":edit["mechanism"]}
    return state


def source_files(state):
    files = {}
    for name, module in sorted(state["modules"].items()):
        direct = ""
        for d in module["declarations"]:
            parameters = ", ".join(p["name"] + ": int" + ("" if p["required"] else " = 0") for p in d["parameters"])
            direct += f"def {d.get('name', d['id'])}({parameters}) -> int:\n    return value\n"
        direct = direct or "# direct binding absent\n"
        forward = "# forwarding slot\n"
        if module.get("forward"):
            f = module["forward"]
            statement = f"from {f['module']} import {f['symbol']} as {f['symbol']}\n"
            if f["guarded"]:
                statement = "try:\n    " + statement + "except ImportError:\n    pass\n"
            forward += statement
        if module.get("open"):
            o = module["open"]
            if o["mechanism"] == "wildcard":
                direct = f"from {o['module']} import *\n"
            elif o["mechanism"] == "dynamic":
                direct = ("from typing import Any\n" + f"from {o['module']} import f as _provided_f\n"
                          "def __getattr__(name: str) -> Any:\n    if name == 'f':\n        return _provided_f\n    raise AttributeError(name)\n")
            else:
                raise ValueError("Unsupported open namespace mechanism")
        files[name + ".py"] = (direct + GAP + forward + module.get("forward_comment", "")).encode()
    sites = {}
    for site, use in sorted(state["uses"].items()):
        path = use["file"] + ".py"
        if path in files:
            raise ValueError("Use file collides with declaration module")
        module, symbol = use["module"], use["symbol"]
        args = ", ".join(str(a) for a in use["arguments"])
        files[path] = f"import {module}\nassert {module}.{symbol}({args}) == 1\n".encode()
        sites[site] = {"path":path, "symbol":module + "." + symbol, "module":module,
                       "start_line":1, "end_line":2}
    return files, sites


def render(template, case):
    base = deepcopy(template["base"])
    files, _ = source_files(base)
    branches, sites = [], {}
    for branch in case["branches"]:
        if branch["parent"] != "target":
            raise ValueError("Python pilot renderer expects independent target-based branches")
        branch_files, branch_sites = source_files(apply(base, branch["edits"]))
        edits = {p:branch_files.get(p) for p in sorted(files.keys() | branch_files.keys()) if files.get(p) != branch_files.get(p)}
        branches.append({"id":branch["id"], "parent":branch["parent"], "files":edits})
        sites.update(branch_sites)
    for site in sites.values():
        site["known_modules"] = sorted(template["base"]["modules"])
    return {"language":"python", "contract":template["contracts"]["python"],
            "base":files, "branches":branches, "sites":sites}

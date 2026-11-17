"""Oracle-label a frozen PUBLIC development selection; excludes private holdout."""

from .paths import resolve
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from .corpus import build_case, candidates


def build_repository(screen, output, python, checker, families, limit=6):
    """Search a pre-frozen candidate list; retain every exclusion for audit."""
    functions = candidates(Path(screen["path"]), screen["roots"])
    accepted, exclusions = [], []
    tried = set()
    for round_index in range(len(functions)):
        for family_index, family in enumerate(families):
            candidate = functions[(round_index + family_index) % len(functions)]
            identity = (candidate["path"], "module" if family == "module_move" else candidate["name"], family)
            if identity in tried:
                continue
            tried.add(identity)
            ordinal = len(tried)
            directory = output / screen["repository"].replace("/", "--") / f"attempt-{ordinal:03d}"
            row = build_case(screen, candidate, family, "positive", directory, python, checker)
            if row is None or not row.get("eligible"):
                exclusions.append(row or {"eligible": False, "exclusion": "mutation not applicable", "family": family})
                continue
            controls = []
            for kind in ("compatible", "unrelated", "coordinated"):
                control = build_case(screen, candidate, family, kind, directory.parent / f"attempt-{ordinal:03d}-{kind}", python, checker)
                controls.append(control)
            if not all(control and control.get("eligible") for control in controls):
                exclusions.append({"eligible": False, "exclusion": "control failed eligibility", "family": family,
                                   "positive": row, "controls": controls})
                continue
            accepted.extend([row, *controls])
            if len(accepted) >= limit * 4:
                break
        if len(accepted) >= limit * 4:
            break
    return {"repository": screen["repository"], "cases": accepted, "excluded": exclusions,
            "retained_positives": sum(row["kind"] == "positive" for row in accepted)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--checker", required=True)
    args = parser.parse_args()
    selected = resolve(json.loads(args.selection.read_text()))
    families = ("remove_attribute", "required_keyword", "unknown_keyword", "too_many_positional", "required_posonly", "module_move")
    with ThreadPoolExecutor(max_workers=3) as executor:
        rows = list(executor.map(lambda screen: build_repository(screen, args.output, args.python, args.checker, families), selected))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "corpus.json").write_text(json.dumps(rows, sort_keys=True, indent=2))
    print(json.dumps({"repositories": len(rows), "positives": sum(row["retained_positives"] for row in rows),
                      "controls": sum(len(row["cases"]) - row["retained_positives"] for row in rows), "split": "development"}))


if __name__ == "__main__":
    main()

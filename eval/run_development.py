"""Evaluate public labelled development cases; never reads the private holdout."""

from .paths import resolve
from .portable import portable
from .paths import locations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

from .measure import evaluate, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("eval/development/cases.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/validation/v04-development-results.json"))
    parser.add_argument("--detector-python", default=resolve('${PYTHON314}'))
    args = parser.parse_args()
    args.detector_python = resolve(args.detector_python)
    cases = resolve(json.loads(args.corpus.read_text()))["cases"]
    source = Path(__file__).resolve().parents[1] / "src"
    fingerprints = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*.py")}
    with ThreadPoolExecutor(max_workers=3) as executor:
        rows = list(executor.map(lambda case: evaluate(case, args.detector_python, source), cases))
    for row, case in zip(rows, cases, strict=True):
        row["id"] = case["id"]
    result = {"stratum": "mutation", "split": "development", "metrics": report(rows), "rows": rows,
              "source_sha256": fingerprints,
              "source_stable": fingerprints == {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*.py")}}
    args.output.write_text(json.dumps(portable(result, locations()), sort_keys=True, indent=2) + "\n")
    print(json.dumps({"micro": result["metrics"]["micro"], "source_stable": result["source_stable"]}))


if __name__ == "__main__":
    main()

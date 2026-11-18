"""Replace machine-specific path prefixes without changing labels or evidence.

Public mappings expand through eval.paths; custom cache locations stay in the
external CROSSWIRE_EVAL_LOCATIONS JSON map. Mutation patches/source stay intact.
"""
import argparse
import json
from pathlib import Path
import re

from .paths import locations

CODE = {'patch', 'patch_A', 'patch_B', 'patch_C', 'patches', 'consumer_source', 'source'}


def portable(value, mapping, key=None):
    if key in CODE:
        return value
    if isinstance(value, dict):
        return {k: portable(v, mapping, k) for k, v in value.items()}
    if isinstance(value, list):
        return [portable(v, mapping, key) for v in value]
    if isinstance(value, str):
        # Longest prefix wins; existing portable tokens are never rewritten.
        choices = {}
        for token, path in mapping.items():
            if isinstance(path, str) and Path(path).is_absolute():
                choices.setdefault(path.rstrip('/'), token)
        if not choices:
            return value
        prefixes = sorted(choices, key=len, reverse=True)
        pattern = re.compile(r'(?<![A-Za-z0-9_/$}])(?:' + '|'.join(re.escape(p) for p in prefixes) + r')(?=/|[\s\x22\x27`),;:]|$)')
        return pattern.sub(lambda m: choices[m[0]], value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+')
    args = parser.parse_args()
    mapping = locations()
    for path in args.files:
        data = json.loads(path.read_text())
        path.write_text(json.dumps(portable(data, mapping), indent=2) + '\n')


if __name__ == '__main__':
    main()

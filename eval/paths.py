"""Expand portable public paths; machine-specific mappings stay outside checkout."""
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

TOKEN = re.compile(r'\$\{[A-Z][A-Z0-9_]*\}')


def locations():
    root = Path(__file__).resolve().parents[1]
    temporary = Path(tempfile.gettempdir())
    defaults = {
        '${HOME}': str(Path.home()),
        '${CHECKOUT}': str(root),
        '${CACHE_DIR}': str(Path.home() / '.crosswire-eval'),
        '${TMP}': str(temporary),
        '${PRIVATE_TMP}': str(temporary.resolve()),
        '${SYSTEM_TMP}': str(temporary),
        '${PYTHON314}': shutil.which('python3.14') or sys.executable,
        '${SYSTEM}': str(Path(os.sep) / 'System'),
        '${LIBRARY}': str(Path(os.sep) / 'Library'),
    }
    brew = shutil.which('brew')
    if brew:
        defaults['${HOMEBREW}'] = str(Path(brew).parent.parent)
    mapping_path = Path(os.environ.get('CROSSWIRE_EVAL_LOCATIONS', Path.home() / '.crosswire-eval/locations.json'))
    if mapping_path.exists():
        defaults.update(json.loads(mapping_path.read_text()))
    return defaults


def resolve(value):
    mapping = locations()
    def visit(item):
        if isinstance(item, dict):
            return {k: visit(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [visit(v) for v in item]
        if isinstance(item, str):
            # Expand token names, not arbitrary substrings in mapped path values.
            for _ in range(10):
                expanded = TOKEN.sub(lambda m: mapping.get(m[0], m[0]), item)
                if expanded == item:
                    return item
                item = expanded
            raise ValueError('Cyclic public location mapping')
        return item
    return visit(value)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path)
    parser.add_argument('--text', action='store_true', help='Expand prose/recorded command strings instead of JSON')
    args = parser.parse_args()
    content = args.file.read_text()
    print(resolve(content) if args.text else json.dumps(resolve(json.loads(content)), indent=2))

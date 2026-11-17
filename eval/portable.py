"""Remove host-specific temporary prefixes from public evidence and configs.

Exact mutation patches/source are left byte-identical. Location mappings are local
and public-development-only; they never include a holdout identity.
"""
import argparse
import json
import re
from pathlib import Path

TEMP=re.compile(r'/(?:private/)?tmp/([A-Za-z0-9_.-]+)')
CODE={'patch','patch_A','patch_B','patch_C','patches','consumer_source','source'}


def portable(value,mapping,key=None):
    if key in CODE:return value
    if isinstance(value,dict):return {k:portable(v,mapping,k) for k,v in value.items()}
    if isinstance(value,list):return [portable(v,mapping,key) for v in value]
    if isinstance(value,str):
        def replace(match):
            name=match.group(1)
            token='${CACHE_'+re.sub('[^A-Za-z0-9]','_',name).upper()+'}'
            mapping[token]=str(Path('/tmp')/name)
            return token
        return TEMP.sub(replace,value)
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('files',type=Path,nargs='+');args=p.parse_args()
    path=Path.home()/'.crosswire-eval/locations.json';path.parent.mkdir(exist_ok=True)
    mapping=json.loads(path.read_text()) if path.exists() else {}
    mapping.update({'${LIVE_HTTPX}':'/tmp/crosswire-field-httpx','${LIVE_DJANGO}':'/tmp/crosswire-v03-django','${LIVE_FLASK}':'/tmp/crosswire-v03-flask'})
    for f in args.files:
        data=json.loads(f.read_text());f.write_text(json.dumps(portable(data,mapping),indent=2)+'\n')
    path.write_text(json.dumps(mapping,indent=2)+'\n')


if __name__=='__main__':main()

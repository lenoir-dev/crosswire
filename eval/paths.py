"""Resolve portable public cache tokens; host mappings stay outside the checkout."""
import json
import os
from pathlib import Path


def resolve(value):
    mapping_path=Path(os.environ.get('CROSSWIRE_EVAL_LOCATIONS',Path.home()/'.crosswire-eval/locations.json'))
    mapping=json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    def visit(item):
        if isinstance(item,dict):return {k:visit(v) for k,v in item.items()}
        if isinstance(item,(list,tuple)):return [visit(v) for v in item]
        if isinstance(item,str):
            for token,path in mapping.items():item=item.replace(token,path)
        return item
    return visit(value)

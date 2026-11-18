"""Compatibility exports for the Python adapter (retained through T21 verification)."""

from .lang.python.analyzer import (
    module_name_for_path, extract_symbols, definition_dumps, extract_references,
    cached_references, valid_syntax, open_module, _params, _shape, _target_names,
    _module_statements, _import_names, _reference_data,
)

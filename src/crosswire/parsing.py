"""Shared boundaries for failures while parsing untrusted Python sources."""

PARSE_ERRORS = (SyntaxError, RecursionError, ValueError, MemoryError)

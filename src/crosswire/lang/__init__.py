"""Language adapters; the core never imports parser implementations directly."""


def adapters_for(repo):
    """The T21 registry deliberately enables only the always-present adapter."""
    from .python.adapter import PythonAdapter
    return {'python': PythonAdapter(repo)}

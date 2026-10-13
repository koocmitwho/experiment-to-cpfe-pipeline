"""Public local harness. Computational pipeline APIs remain independent."""
__all__ = ['HarnessClient', 'initialize_workspace', 'approve_handoff']


def __getattr__(name):
    if name in __all__:
        from . import service
        return getattr(service, name)
    raise AttributeError(name)

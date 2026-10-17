"""A deliberately narrow, detached read facade; no execution or adapter access."""
from app.core import repo

READS = frozenset({"get_task", "list_facts", "list_evidence", "get_evidence", "get_latest_approval", "list_approvals", "get_providers"})


def _detach(value):
    if isinstance(value, list):
        return [_detach(item) for item in value]
    return value.model_copy(deep=True) if hasattr(value, "model_copy") else value


class ReadOnlyRepo:
    __slots__ = ()

    def __getattr__(self, name):
        if name not in READS:
            raise AttributeError(f"Read-only repository does not expose {name}")
        def read(*args, **kwargs):
            return _detach(getattr(repo, name)(*args, **kwargs))
        return read

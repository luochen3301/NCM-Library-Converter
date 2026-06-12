def dump(*args, **kwargs):
    from .core import dump as _dump

    return _dump(*args, **kwargs)


__all__ = ["dump"]

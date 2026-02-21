"""Shared helpers for Tool API write-operation modules."""


class _ApiProxy:
    def __getattr__(self, name):
        from .. import tool_api as _api_mod

        return getattr(_api_mod, name)


api = _ApiProxy()
from __future__ import annotations
from srxsync.inventory import Auth
from srxsync.secrets.base import Secret, SecretError, SecretProvider

_PROVIDERS: dict[str, type[SecretProvider]] = {}


def _register_defaults() -> None:
    from srxsync.secrets.env import EnvProvider
    from srxsync.secrets.netrc_provider import NetrcProvider
    _PROVIDERS["env"] = EnvProvider
    _PROVIDERS["netrc"] = NetrcProvider


def get_secret(host: str, auth: Auth) -> Secret:
    if not _PROVIDERS:
        _register_defaults()
    cls = _PROVIDERS.get(auth.provider)
    if cls is None:
        raise SecretError(f"unknown provider: {auth.provider}")
    return cls().get(host=host, auth=auth)


__all__ = ["Secret", "SecretError", "SecretProvider", "get_secret"]

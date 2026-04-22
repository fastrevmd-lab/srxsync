from __future__ import annotations

from srxsync.inventory import Auth
from srxsync.secrets.base import Secret, SecretError, SecretProvider

_PROVIDERS: dict[str, type[SecretProvider]] = {}


def _register_defaults() -> None:
    from srxsync.secrets.env import EnvProvider
    from srxsync.secrets.keyring_provider import KeyringProvider
    from srxsync.secrets.netrc_provider import NetrcProvider
    from srxsync.secrets.vault import VaultProvider

    _PROVIDERS["env"] = EnvProvider
    _PROVIDERS["netrc"] = NetrcProvider
    _PROVIDERS["keyring"] = KeyringProvider
    _PROVIDERS["vault"] = VaultProvider


def get_secret(host: str, auth: Auth) -> Secret:
    if not _PROVIDERS:
        _register_defaults()
    cls = _PROVIDERS.get(auth.provider)
    if cls is None:
        raise SecretError(f"unknown provider: {auth.provider}")
    return cls().get(host=host, auth=auth)


__all__ = ["Secret", "SecretError", "SecretProvider", "get_secret"]

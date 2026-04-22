from __future__ import annotations

import os

from srxsync.inventory import Auth
from srxsync.secrets.base import Secret, SecretError, SecretProvider


def _env_key(prefix: str, host: str) -> str:
    return f"{prefix}_{host.upper().replace('.', '_').replace('-', '_')}"


class EnvProvider(SecretProvider):
    def get(self, host: str, auth: Auth) -> Secret:
        user_key = _env_key("SRX_USER", host)
        pw_key = _env_key("SRX_PASSWORD", host)
        key_key = _env_key("SRX_SSH_KEY", host)
        user = os.environ.get(user_key)
        pw = os.environ.get(pw_key)
        ssh_key = os.environ.get(key_key)
        if user is None:
            raise SecretError(f"missing env var: {user_key}")
        if pw is None and ssh_key is None:
            raise SecretError(
                f"need either {pw_key} or {key_key} for {host}"
            )
        return Secret(
            username=user,
            password=pw,
            ssh_key_path=os.path.expanduser(ssh_key) if ssh_key else None,
        )

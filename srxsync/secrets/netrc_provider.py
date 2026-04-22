from __future__ import annotations
import netrc
from srxsync.inventory import Auth
from srxsync.secrets.base import Secret, SecretError, SecretProvider


class NetrcProvider(SecretProvider):
    def get(self, host: str, auth: Auth) -> Secret:
        try:
            n = netrc.netrc()
        except (FileNotFoundError, netrc.NetrcParseError) as e:
            raise SecretError(f"netrc read failed: {e}") from e
        entry = n.authenticators(host)
        if entry is None:
            raise SecretError(f"no netrc entry for host: {host}")
        login, _account, password = entry
        if login is None:
            raise SecretError(f"netrc entry for {host} has no login")
        return Secret(username=login, password=password)

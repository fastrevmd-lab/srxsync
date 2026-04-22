from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from srxsync.inventory import Auth


class SecretError(RuntimeError):
    """Raised when a secret cannot be resolved."""


@dataclass(frozen=True)
class Secret:
    username: str
    password: str | None = None
    ssh_key_path: str | None = None


class SecretProvider(ABC):
    @abstractmethod
    def get(self, host: str, auth: Auth) -> Secret: ...

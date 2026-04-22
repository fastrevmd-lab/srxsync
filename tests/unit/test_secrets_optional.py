import pytest
from srxsync.inventory import Auth
from srxsync.secrets import get_secret, SecretError


def test_keyring_provider_missing_extra_gives_helpful_error(monkeypatch):
    import srxsync.secrets.keyring_provider as kp
    monkeypatch.setattr(kp, "_keyring", None)
    with pytest.raises(SecretError, match="pip install"):
        kp.KeyringProvider().get(host="x", auth=Auth(provider="keyring", key="x"))


def test_vault_provider_missing_extra_gives_helpful_error(monkeypatch):
    import srxsync.secrets.vault as vp
    monkeypatch.setattr(vp, "_hvac", None)
    with pytest.raises(SecretError, match="pip install"):
        vp.VaultProvider().get(host="x", auth=Auth(provider="vault", path="secret/x"))

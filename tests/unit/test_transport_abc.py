import pytest
from srxsync.transport.base import Transport, TransportError


def test_transport_is_abstract():
    with pytest.raises(TypeError):
        Transport()  # type: ignore[abstract]


def test_transport_has_required_methods():
    required = {"connect", "fetch", "load", "commit_confirmed",
                "confirm", "rollback", "close"}
    assert required.issubset(set(dir(Transport)))


def test_transport_error_is_exception():
    assert issubclass(TransportError, Exception)

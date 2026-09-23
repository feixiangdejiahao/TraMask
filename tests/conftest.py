"""Unit tests use mocked transports; live experiments run through the CLI."""
import socket

import pytest


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Unit tests must mock network transports")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)

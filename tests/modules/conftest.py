import io
import socket
from email.message import Message

import pytest


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"<html>hello</html>", *, code=200, headers=None):
        super().__init__(body)
        self.code = code
        self.headers = Message()
        for key, value in (headers if headers is not None else {"Content-Type": "text/html"}).items():
            self.headers[key] = value
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)

    def info(self):
        return self.headers


class FakeOpener:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def deny_unit_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unit tests must not access the network")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def public_dns():
    def resolve(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", port, 0, 0))]
    return resolve


@pytest.fixture
def response_factory():
    return FakeResponse


@pytest.fixture
def opener_factory():
    return FakeOpener

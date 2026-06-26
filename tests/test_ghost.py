import os

os.environ.setdefault("GHOST_URL", "https://ghost.example")
os.environ.setdefault("GHOST_CONTENT_KEY", "test-key")

import httpx

from glamtool.ghost import GhostContentClient


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"posts": []}


class FakeClient:
    def __init__(self, *, timeout):
        self.timeout = timeout
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params):
        self.calls.append((url, params))
        return FakeResponse()


def test_list_posts_includes_order_when_provided(monkeypatch):
    seen = {}

    def client_factory(*, timeout):
        fake_client = FakeClient(timeout=timeout)
        seen["client"] = fake_client
        return fake_client

    monkeypatch.setattr(httpx, "Client", client_factory)
    client = GhostContentClient("https://ghost.example", "abc123")

    client.list_posts(order="published_at asc")

    _, params = seen["client"].calls[0]
    assert params["order"] == "published_at asc"

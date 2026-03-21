import httpx

from glamtool.ghost import GhostContentClient


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


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
        return FakeResponse(
            {
                "posts": [
                    {
                        "id": "post-1",
                        "title": "Hello",
                        "status": "published",
                        "published_at": "2026-02-27T10:00:00Z",
                        "url": "https://example.com/hello",
                        "feature_image": None,
                        "slug": "hello",
                    }
                ]
            }
        )


def test_list_posts_builds_expected_request(monkeypatch):
    seen = {}

    def client_factory(*, timeout):
        fake_client = FakeClient(timeout=timeout)
        seen["client"] = fake_client
        return fake_client

    monkeypatch.setattr(httpx, "Client", client_factory)
    client = GhostContentClient("https://ghost.example/", "abc123", timeout_s=12.5)

    posts = client.list_posts(limit=999, filter_="status:published", page=3)

    assert len(posts) == 1
    assert posts[0].id == "post-1"
    url, params = seen["client"].calls[0]
    assert url == "https://ghost.example/ghost/api/content/posts/"
    assert params["key"] == "abc123"
    assert params["limit"] == 100
    assert params["page"] == 3
    assert params["filter"] == "status:published"
    assert seen["client"].timeout == 12.5


def test_paginate_posts_stops_after_partial_page(monkeypatch):
    client = GhostContentClient("https://ghost.example", "abc123")
    calls = []

    def fake_list_posts(*, limit, include, fields, filter_, page):
        calls.append(page)
        if page == 1:
            return ["a", "b"]
        if page == 2:
            return ["c"]
        return []

    monkeypatch.setattr(client, "list_posts", fake_list_posts)

    posts = client.paginate_posts(per_page=2, filter_="tag:song-pick", max_pages=5)

    assert posts == ["a", "b", "c"]
    assert calls == [1, 2]

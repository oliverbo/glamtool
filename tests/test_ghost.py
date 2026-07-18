import os

os.environ.setdefault("GHOST_URL", "https://ghost.example")
os.environ.setdefault("GHOST_CONTENT_KEY", "test-key")

import httpx
import jwt

from glamtool.ghost import GhostAdminClient, GhostContentClient


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


class FakeAdminResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeAdminHttpClient:
    def __init__(self, *, timeout, seen):
        self.timeout = timeout
        self.seen = seen

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.seen.append((url, kwargs))
        if url.endswith("images/upload/"):
            return FakeAdminResponse({"images": [{"url": "https://ghost.example/uploaded.png"}]})
        return FakeAdminResponse({"posts": [{"id": "post-id", **kwargs["json"]["posts"][0]}]})


def test_admin_client_uploads_images_and_creates_a_draft(monkeypatch, tmp_path):
    seen = []

    def client_factory(*, timeout):
        return FakeAdminHttpClient(timeout=timeout, seen=seen)

    monkeypatch.setattr(httpx, "Client", client_factory)
    image = tmp_path / "cover.png"
    image.write_bytes(b"image bytes")
    secret = "ab" * 32
    client = GhostAdminClient("https://ghost.example", f"key-id:{secret}")

    uploaded_url = client.upload_image(image)
    post = client.create_draft(
        title="Draft title",
        html="<p>Body</p>",
        tags=["News"],
        authors=["editor@example.com"],
        feature_image=uploaded_url,
    )

    assert uploaded_url == "https://ghost.example/uploaded.png"
    assert post["id"] == "post-id"
    upload_url, upload_call = seen[0]
    assert upload_url == "https://ghost.example/ghost/api/admin/images/upload/"
    assert upload_call["data"]["purpose"] == "image"
    create_url, create_call = seen[1]
    assert create_url == "https://ghost.example/ghost/api/admin/posts/"
    assert create_call["params"] == {"source": "html"}
    assert create_call["json"] == {
        "posts": [
            {
                "title": "Draft title",
                "html": "<p>Body</p>",
                "status": "draft",
                "tags": ["News"],
                "authors": ["editor@example.com"],
                "feature_image": "https://ghost.example/uploaded.png",
            }
        ]
    }
    authorization = create_call["headers"]["Authorization"]
    token = authorization.removeprefix("Ghost ")
    assert jwt.get_unverified_header(token)["kid"] == "key-id"
    assert jwt.decode(token, options={"verify_signature": False})["aud"] == "/admin/"

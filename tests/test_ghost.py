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


def test_content_client_gets_a_post_by_encoded_slug(monkeypatch):
    seen = {}

    class SlugResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "posts": [
                    {
                        "id": "post-id",
                        "title": "A post",
                        "status": "published",
                        "url": "https://ghost.example/a post/",
                        "slug": "a post",
                        "html": "<p>Body</p>",
                    }
                ]
            }

    class SlugClient(FakeClient):
        def get(self, url, params):
            seen["call"] = (url, params)
            return SlugResponse()

    monkeypatch.setattr(httpx, "Client", lambda *, timeout: SlugClient(timeout=timeout))

    post = GhostContentClient("https://ghost.example", "abc123").get_post_by_slug("a post")

    assert post.id == "post-id"
    url, params = seen["call"]
    assert url.endswith("/posts/slug/a%20post/")
    assert params["key"] == "abc123"
    assert "html" in params["fields"]


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


def test_admin_client_fetches_and_updates_post_html(monkeypatch):
    seen = []

    class UpdateHttpClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url, **kwargs):
            seen.append(("get", url, kwargs))
            return FakeAdminResponse(
                {
                    "posts": [
                        {
                            "id": "post/id",
                            "html": '<img src="old.jpg">',
                            "updated_at": "2026-08-26T12:00:00.000Z",
                        }
                    ]
                }
            )

        def put(self, url, **kwargs):
            seen.append(("put", url, kwargs))
            return FakeAdminResponse({"posts": [{"id": "post/id", **kwargs["json"]["posts"][0]}]})

    monkeypatch.setattr(httpx, "Client", UpdateHttpClient)
    secret = "ab" * 32
    client = GhostAdminClient("https://ghost.example", f"key-id:{secret}")

    post = client.get_post("post/id")
    updated = client.update_post_html(
        "post/id",
        html='<img src="new.jpg">',
        updated_at=post["updated_at"],
    )

    assert updated["html"] == '<img src="new.jpg">'
    method, get_url, get_call = seen[0]
    assert method == "get"
    assert get_url.endswith("/posts/post%2Fid/")
    assert get_call["params"] == {"formats": "html"}
    method, put_url, put_call = seen[1]
    assert method == "put"
    assert put_url.endswith("/posts/post%2Fid/")
    assert put_call["params"] == {"source": "html"}
    assert put_call["json"] == {
        "posts": [
            {
                "html": '<img src="new.jpg">',
                "updated_at": "2026-08-26T12:00:00.000Z",
            }
        ]
    }


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
        feature_image_alt="Cover alt text",
        feature_image_caption="Cover caption",
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
                "feature_image_alt": "Cover alt text",
                "feature_image_caption": "Cover caption",
            }
        ]
    }
    authorization = create_call["headers"]["Authorization"]
    token = authorization.removeprefix("Ghost ")
    assert jwt.get_unverified_header(token)["kid"] == "key-id"
    assert jwt.decode(token, options={"verify_signature": False})["aud"] == "/admin/"

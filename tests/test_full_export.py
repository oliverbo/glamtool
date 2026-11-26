import os
from dataclasses import replace

os.environ.setdefault("GHOST_URL", "https://ghost.example")
os.environ.setdefault("GHOST_CONTENT_KEY", "test-key")

import httpx
import pytest
from typer.testing import CliRunner

from glamtool import cli
from glamtool.exporter import ExportError, export_post
from glamtool.ghost import GhostContentClient, GhostPost


@pytest.fixture
def post():
    return GhostPost("abc123", "A title", "published", "2026-01-01T10:00:00Z",
                     "https://ghost.example/a-post/", "/Cover Image.JPG", "a-post",
                     '<p>Hello</p><figure><img src="/inside.png" alt="A chart" '
                     'srcset="/inside.png 1x, /large.png 2x"><figcaption>Caption</figcaption></figure>'
                     '<img src="/inside.png"><img src="/Cover Image.JPG">')


def test_localizes_all_images_and_deduplicates(post, tmp_path):
    seen = []

    def respond(request):
        seen.append(request.url.path)
        kind = "image/jpeg" if request.url.path.endswith("JPG") else "image/png"
        return httpx.Response(200, headers={"Content-Type": kind}, content=b"image")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        folder = export_post(post, tmp_path, client)
    assert folder.name == "2026-01-01-a-post-abc123"
    markdown = (folder / "post.md").read_text()
    assert "# A title" in markdown
    assert "Original: https://ghost.example/a-post/" in markdown
    assert "![A chart](images/image-002.png)" in markdown
    assert "Caption" in markdown
    assert markdown.count("images/feature.jpg") == 2
    assert sorted(p.name for p in (folder / "images").iterdir()) == [
        "feature.jpg", "image-002.png", "image-003.png"]
    assert seen == ["/Cover Image.JPG", "/inside.png", "/large.png"]
    assert list(tmp_path.iterdir()) == [folder]


@pytest.mark.parametrize("status,media,body", [(404, "image/png", b"x"),
                                               (200, "text/html", b"error"),
                                               (200, "image/png", b"")])
def test_failed_download_leaves_no_partial_folder(post, tmp_path, status, media, body):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(
        status, headers={"Content-Type": media}, content=body))) as client:
        with pytest.raises((ExportError, httpx.HTTPError)):
            export_post(post, tmp_path, client)
    assert list(tmp_path.iterdir()) == []


def test_existing_backup_is_preserved_and_missing_html_fails(post, tmp_path):
    post = replace(post, feature_image=None, html="")
    with httpx.Client() as client:
        folder = export_post(post, tmp_path, client)
        with pytest.raises(ExportError, match="already exists"):
            export_post(post, tmp_path, client)
        with pytest.raises(ExportError, match="HTML is missing"):
            export_post(replace(post, html=None), tmp_path, client)
    assert (folder / "post.md").exists()


def test_bounded_pagination_stops_at_count(monkeypatch):
    seen = []

    def batch(self, **kwargs):
        seen.append(kwargs)
        return list(range((kwargs["page"] - 1) * 100, kwargs["page"] * 100))

    monkeypatch.setattr(GhostContentClient, "list_posts", batch)
    result = GhostContentClient("https://ghost.example", "key").paginate_posts(count=101)
    assert result == list(range(101))
    assert len(seen) == 2


def test_command_filters_and_continues_after_failure(monkeypatch, tmp_path, post):
    seen = {}

    class Client:
        def paginate_posts(self, **kwargs):
            seen.update(kwargs)
            return [replace(post, html=None), replace(post, id="second", html="", feature_image=None)]

    monkeypatch.setattr(cli, "ghost_client", Client)
    result = CliRunner().invoke(cli.app, ["export-full-posts", "--start-date", "2026-01-01",
        "--count", "2", "--tag", "music", "--out", str(tmp_path)])
    assert result.exit_code == 1, result.output
    assert "Exported 1 post(s); 1 failed" in result.stdout
    assert seen["count"] == 2
    assert seen["filter_"] == "status:published+tag:music+published_at:>='2026-01-01'"
    assert seen["order"] == "published_at asc,id asc"
    assert "feature_image" in seen["fields"]
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("arguments", [["--count", "0"], ["--start-date", "oops"],
    ["--start-date", "2026-02-01", "--end-date", "2026-01-01"]])
def test_invalid_options_do_not_call_api(monkeypatch, arguments):
    monkeypatch.setattr(cli, "ghost_client", lambda: pytest.fail("API should not be called"))
    assert CliRunner().invoke(cli.app, ["export-full-posts", *arguments]).exit_code == 2


def test_feature_metadata_and_video_sources(post, tmp_path):
    post = replace(post, feature_image_alt="Cover ] text", feature_image_caption="<b>Credit</b>",
                   html='<video><source src="/video.mp4" type="video/mp4"></video>')
    seen = []

    def respond(request):
        seen.append(request.url.path)
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"image")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        folder = export_post(post, tmp_path, client)
    text = (folder / "post.md").read_text()
    assert "![Cover \\] text](images/feature.jpg)" in text
    assert "**Credit**" in text
    assert seen == ["/Cover Image.JPG"]


def test_no_matches_is_success(monkeypatch, tmp_path):
    class Client:
        def paginate_posts(self, **kwargs):
            return []

    monkeypatch.setattr(cli, "ghost_client", Client)
    result = CliRunner().invoke(cli.app, ["export-full-posts", "--out", str(tmp_path / "backup")])
    assert result.exit_code == 0
    assert "Exported 0 post(s); 0 failed" in result.stdout
    assert not (tmp_path / "backup").exists()

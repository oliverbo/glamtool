import os

os.environ.setdefault("GHOST_URL", "https://ghost.example")
os.environ.setdefault("GHOST_CONTENT_KEY", "test-key")

from typer.testing import CliRunner

from glamtool import cli
from glamtool.ghost import GhostPost


runner = CliRunner()


def test_build_published_at_filter_for_week():
    assert (
        cli.build_published_at_filter(start_date=None, end_date=None, week="2026-06-18")
        == "published_at:>='2026-06-18'+published_at:<'2026-06-25'"
    )


def test_html_to_markdown_converts_common_post_formatting():
    html = """
    <p>Listen to <a href="https://example.com/song">the song</a>.</p>
    <blockquote><p>A quoted line</p></blockquote>
    <p><strong>Bold</strong> and <em>italic</em>.</p>
    <figure><iframe src="https://www.youtube.com/embed/abc123?feature=oembed"></iframe></figure>
    """

    assert cli.html_to_markdown(html) == (
        "Listen to [the song](https://example.com/song).\n\n"
        "> A quoted line\n\n"
        "**Bold** and *italic*.\n\n"
        "https://www.youtube.com/watch?v=abc123"
    )


def test_export_markdown_header_writes_linked_titles_and_requests_html(monkeypatch, tmp_path):
    posts = [
        GhostPost(
            id="1",
            title="Song Pick: Robyn - Dancing On My Own",
            status="published",
            published_at="2026-06-23T10:00:00Z",
            url="https://example.com/robyn",
            feature_image=None,
            slug="robyn",
            html="<p>Body</p>",
        ),
        GhostPost(
            id="2",
            title="Song Pick: MUNA - Number One Fan",
            status="published",
            published_at="2026-06-24T10:00:00Z",
            url="https://example.com/muna",
            feature_image=None,
            slug="muna",
            html="<p>Body</p>",
        )
    ]
    seen = {}

    class FakeClient:
        def paginate_posts(self, filter_=None, fields=None, order=None):
            seen["filter"] = filter_
            seen["fields"] = fields
            seen["order"] = order
            return posts

    monkeypatch.setattr(cli, "ghost_client", lambda: FakeClient())
    out = tmp_path / "song_picks.md"

    result = runner.invoke(
        cli.app,
        [
            "export-markdown",
            "--format",
            "header",
            "--tag",
            "song-pick",
            "--week",
            "2026-06-18",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == (
        "- [Song Pick: Robyn - Dancing On My Own](https://example.com/robyn)\n"
        "- [Song Pick: MUNA - Number One Fan](https://example.com/muna)\n"
    )
    assert seen["fields"] == cli.MARKDOWN_POST_FIELDS
    assert seen["order"] == "published_at asc"
    assert seen["filter"] == (
        "status:published+tag:song-pick+published_at:>='2026-06-18'+published_at:<'2026-06-25'"
    )


def test_publish_command_creates_a_draft(monkeypatch, tmp_path):
    source = tmp_path / "draft.md"
    source.write_text(
        "---\ntags: [News]\nauthors: editor@example.com\n---\n# Draft title\n\nBody\n",
        encoding="utf-8",
    )
    seen = {}

    class FakeAdminClient:
        def create_draft(self, **kwargs):
            seen.update(kwargs)
            return {"id": "draft-id", "title": kwargs["title"]}

    monkeypatch.setattr(cli, "ghost_admin_client", lambda: FakeAdminClient())

    result = runner.invoke(cli.app, ["publish", str(source)])

    assert result.exit_code == 0, result.output
    assert "Created Ghost draft: Draft title" in result.output
    assert "ID: draft-id" in result.output
    assert seen == {
        "title": "Draft title",
        "html": "<p>Body</p>",
        "tags": ["News"],
        "authors": ["editor@example.com"],
        "feature_image": None,
    }


def test_publish_command_uploads_bare_content_block_images(monkeypatch, tmp_path):
    cover = tmp_path / "cover image.jpg"
    cover.write_bytes(b"cover")
    inside = tmp_path / "inside.png"
    inside.write_bytes(b"inside")
    source = tmp_path / "draft.md"
    source.write_text(
        "# Draft title\n\ncover image.jpg\n\nBody\n\ninside.png\n",
        encoding="utf-8",
    )
    seen = {"uploads": []}

    class FakeAdminClient:
        def upload_image(self, path):
            seen["uploads"].append(path)
            return f"https://ghost.example/{path.name.replace(' ', '-')}"

        def create_draft(self, **kwargs):
            seen["draft"] = kwargs
            return {"id": "draft-id", "title": kwargs["title"]}

    monkeypatch.setattr(cli, "ghost_admin_client", lambda: FakeAdminClient())

    result = runner.invoke(cli.app, ["publish", str(source)])

    assert result.exit_code == 0, result.output
    assert seen["uploads"] == [cover.resolve(), inside.resolve()]
    assert seen["draft"]["feature_image"] == "https://ghost.example/cover-image.jpg"
    assert "cover-image.jpg" not in seen["draft"]["html"]
    assert 'src="https://ghost.example/inside.png"' in seen["draft"]["html"]


def test_publish_command_requires_an_admin_key(monkeypatch, tmp_path):
    source = tmp_path / "draft.md"
    source.write_text("# Draft title\n\nBody\n", encoding="utf-8")
    monkeypatch.setattr(cli.settings, "ghost_admin_key", None)

    result = runner.invoke(cli.app, ["publish", str(source)])

    assert result.exit_code == 1
    assert "GHOST_ADMIN_KEY is required" in result.output

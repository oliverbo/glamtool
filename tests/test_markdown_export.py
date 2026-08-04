import os

os.environ.setdefault("GHOST_URL", "https://ghost.example")
os.environ.setdefault("GHOST_CONTENT_KEY", "test-key")

import pytest
from typer.testing import CliRunner

from glamtool import cli
from glamtool.glamglare import GlamglareArtist
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


def test_parse_song_pick_title_preserves_hyphens_in_song_name():
    assert cli.parse_song_pick_title("Song Pick: Robyn - Dancing - On My Own") == (
        "Robyn",
        "Dancing - On My Own",
    )


def test_glamglare_client_requires_configuration_only_when_used(monkeypatch):
    monkeypatch.setattr(cli.settings, "gg_api_url", None)
    monkeypatch.setattr(cli.settings, "gg_api_secret", None)

    with pytest.raises(cli.InstagramRollCallError, match="GG_API_URL and GG_API_SECRET"):
        cli.glamglare_client()


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


def test_export_markdown_instagram_writes_roll_call_and_caches_artists(monkeypatch, tmp_path):
    posts = [
        GhostPost(
            id="1",
            title="Song Pick: Robyn - Dancing On My Own",
            status="published",
            published_at="2026-06-23T10:00:00Z",
            url=None,
            feature_image=None,
            slug="robyn-one",
        ),
        GhostPost(
            id="2",
            title="Robyn - Honey",
            status="published",
            published_at="2026-06-24T10:00:00Z",
            url=None,
            feature_image=None,
            slug="robyn-two",
        ),
    ]
    seen = {"artists": []}

    class FakeGhostClient:
        def paginate_posts(self, filter_=None, fields=None, order=None):
            seen["filter"] = filter_
            seen["fields"] = fields
            seen["order"] = order
            return posts

    class FakeGlamglareClient:
        def find_artist(self, name):
            seen["artists"].append(name)
            return GlamglareArtist(name="Robyn", instagram_handle="@robynkonichiwa")

    monkeypatch.setattr(cli, "ghost_client", FakeGhostClient)
    monkeypatch.setattr(cli, "glamglare_client", FakeGlamglareClient)
    out = tmp_path / "instagram.md"

    result = runner.invoke(
        cli.app,
        [
            "export-markdown",
            "--format",
            "instagram",
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
        "- @robynkonichiwa - Dancing On My Own\n- @robynkonichiwa - Honey\n"
    )
    assert seen["artists"] == ["Robyn"]
    assert seen["fields"] == cli.MARKDOWN_POST_FIELDS
    assert seen["order"] == "published_at asc"
    assert seen["filter"] == (
        "status:published+tag:song-pick+published_at:>='2026-06-18'+published_at:<'2026-06-25'"
    )


def test_export_markdown_instagram_reports_all_unresolved_posts_without_writing(
    monkeypatch, tmp_path
):
    posts = [
        GhostPost("1", "Bad title", "published", None, None, None, None),
        GhostPost("2", "Song Pick: Unknown - A Song", "published", None, None, None, None),
        GhostPost("3", "Song Pick: Known - Another Song", "published", None, None, None, None),
    ]

    class FakeGhostClient:
        def paginate_posts(self, **_kwargs):
            return posts

    class FakeGlamglareClient:
        def find_artist(self, name):
            if name == "Known":
                return GlamglareArtist(name="Known", instagram_handle=None)
            return None

    monkeypatch.setattr(cli, "ghost_client", FakeGhostClient)
    monkeypatch.setattr(cli, "glamglare_client", FakeGlamglareClient)
    out = tmp_path / "instagram.md"

    result = runner.invoke(
        cli.app,
        ["export-markdown", "--format", "instagram", "--out", str(out)],
    )

    assert result.exit_code == 1
    assert "Bad title" in result.output
    assert "artist 'Unknown' was not found" in result.output
    assert "artist 'Known' has no Instagram handle" in result.output
    assert not out.exists()


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

import os

os.environ.setdefault("GHOST_URL", "https://ghost.example")
os.environ.setdefault("GHOST_CONTENT_KEY", "test-key")

from typer.testing import CliRunner

from glamtool import cli
from glamtool.ghost import GhostPost


runner = CliRunner()


def test_build_published_at_filter_for_week():
    assert (
        cli.build_published_at_filter(start_date=None, end_date=None, week="2026-06-25")
        == "published_at:>='2026-06-22'+published_at:<'2026-06-29'"
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
        )
    ]
    seen = {}

    class FakeClient:
        def paginate_posts(self, filter_=None, fields=None):
            seen["filter"] = filter_
            seen["fields"] = fields
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
            "2026-06-25",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == "- [Song Pick: Robyn - Dancing On My Own](https://example.com/robyn)\n"
    assert seen["fields"] == cli.MARKDOWN_POST_FIELDS
    assert seen["filter"] == (
        "status:published+tag:song-pick+published_at:>='2026-06-22'+published_at:<'2026-06-29'"
    )

import csv

from typer.testing import CliRunner

from glamtool import cli
from glamtool.ghost import GhostPost


runner = CliRunner()


def test_export_posts_smart_writes_csv_with_parsed_song_fields(monkeypatch, tmp_path):
    exported_posts = [
        GhostPost(
            id="1",
            title="SONG PICK: Robyn - Dancing On My Own [VIDEO]",
            status="published",
            published_at="2026-02-27T13:45:09Z",
            url="https://example.com/post-1",
            feature_image=None,
            slug="post-1",
        )
    ]

    class FakeClient:
        def paginate_posts(self, filter_=None):
            assert filter_ == "status:published+tag:song-pick"
            return exported_posts

    monkeypatch.setattr(cli, "ghost_client", lambda ctx: FakeClient())
    out_file = tmp_path / "exports" / "song_picks.csv"

    result = runner.invoke(cli.app, ["export-posts", "--smart", "--tag", "song-pick", "--out", str(out_file)])

    assert result.exit_code == 0, result.output
    assert "Exported 1 posts" in result.output
    with out_file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows == [
        ["id", "title", "published_at", "url", "feature_image", "slug", "artist", "song_title"],
        [
            "1",
            "SONG PICK: Robyn - Dancing On My Own [VIDEO]",
            "2026-02-27 13:45:09",
            "https://example.com/post-1",
            "",
            "post-1",
            "Robyn",
            "Dancing On My Own",
        ],
    ]


def test_sanity_returns_exit_code_1_when_api_call_fails(monkeypatch):
    class FakeClient:
        def list_posts(self, limit=1):
            raise RuntimeError("boom")

    monkeypatch.setattr(cli, "ghost_client", lambda ctx: FakeClient())

    result = runner.invoke(cli.app, ["sanity"])

    assert result.exit_code == 1
    assert "Ghost API call failed" in result.output

import os

os.environ.setdefault("GHOST_URL", "https://ghost.example")
os.environ.setdefault("GHOST_CONTENT_KEY", "test-key")

from typer.testing import CliRunner

from glamtool import cli
from glamtool.ghost import GhostPost
from glamtool.image_repair import (
    SrcsetCandidate,
    parse_srcset,
    repair_embedded_images,
    wordpress_original_url,
)


runner = CliRunner()


def test_wordpress_original_url_preserves_query_fragment_and_filename_hyphens():
    assert wordpress_original_url(
        "https://cdn.example/my-photo-2026-tour-1024x742.JPEG?download=1#hero"
    ) == "https://cdn.example/my-photo-2026-tour.JPEG?download=1#hero"
    assert wordpress_original_url("https://cdn.example/my-photo-2026-tour.jpg") is None


def test_parse_srcset_retains_a_comma_inside_a_query_string():
    assert parse_srcset(
        "https://cdn.example/a.jpg?crop=1,2 1x, https://cdn.example/a@2x.jpg 2x"
    ) == [
        SrcsetCandidate("https://cdn.example/a.jpg?crop=1,2", "1x"),
        SrcsetCandidate("https://cdn.example/a@2x.jpg", "2x"),
    ]


def test_repair_uses_verified_original_and_removes_broken_responsive_attributes():
    html = (
        '<p class="before">Keep &amp; preserve</p>'
        '<img loading="lazy" width="710" '
        'src="https://cdn.example/mothica-at-show-1024x742.jpg" '
        'alt="A &amp; B" '
        'srcset="https://cdn.example/mothica-at-show-300x217.jpg 300w, '
        'https://cdn.example/mothica-at-show-710x514.jpg 710w" '
        'sizes="(max-width: 710px) 100vw, 710px" />'
        "<section>Untouched</section>"
    )
    working = {"https://cdn.example/mothica-at-show.jpg"}

    result = repair_embedded_images(
        html,
        post_url="https://site.example/posts/example/",
        check_url=lambda url: url in working,
    )

    assert result.checked == 1
    assert result.repaired == 1
    assert result.skipped == 0
    assert result.broken == 0
    assert 'src="https://cdn.example/mothica-at-show.jpg"' in result.html
    assert "srcset=" not in result.html
    assert "sizes=" not in result.html
    assert 'loading="lazy"' in result.html
    assert 'width="710"' in result.html
    assert 'alt="A &amp; B"' in result.html
    assert result.html.startswith('<p class="before">Keep &amp; preserve</p>')
    assert result.html.endswith("<section>Untouched</section>")


def test_repair_keeps_only_valid_srcset_candidates_and_uses_one_as_src_fallback():
    html = (
        '<img src="/missing.jpg" '
        'srcset="/valid.jpg?crop=1,2 1x, /missing@2x.jpg 2x" sizes="100vw">'
    )

    result = repair_embedded_images(
        html,
        post_url="https://site.example/post/",
        check_url=lambda url: url == "https://site.example/valid.jpg?crop=1,2",
    )

    assert result.repaired == 1
    assert result.broken == 0
    assert 'src="/valid.jpg?crop=1,2"' in result.html
    assert 'srcset="/valid.jpg?crop=1,2 1x"' in result.html
    assert 'sizes="100vw"' in result.html


def test_repair_is_an_exact_no_op_for_valid_non_wordpress_images():
    html = "<figure>\n<IMG data-id='7' SRC='https://cdn.example/photo.jpg' alt='ok'>\n</figure>"

    result = repair_embedded_images(
        html,
        post_url="https://site.example/post/",
        check_url=lambda url: True,
    )

    assert result.html == html
    assert result.checked == 1
    assert result.repaired == 0
    assert result.skipped == 1
    assert result.broken == 0


def test_repair_reports_failed_fallback_without_returning_a_partial_tag_change():
    html = '<img src="/photo-300x200.png" srcset="/also-missing.png 2x" sizes="50vw">'

    result = repair_embedded_images(
        html,
        post_url="https://site.example/post/",
        check_url=lambda url: False,
    )

    assert result.html == html
    assert result.checked == 1
    assert result.repaired == 0
    assert result.skipped == 0
    assert result.broken == 1


def test_repair_handles_multiple_images_and_caches_duplicate_checks():
    html = '<img src="/ok.jpg"><img src="/ok.jpg"><img src="data:image/gif;base64,AAAA">'
    checked = []

    result = repair_embedded_images(
        html,
        post_url="https://site.example/post/",
        check_url=lambda url: checked.append(url) is None or True,
    )

    assert result.checked == 3
    assert result.skipped == 3
    assert checked == ["https://site.example/ok.jpg"]


def test_repair_post_images_command_updates_the_current_admin_post(monkeypatch):
    content_post = GhostPost(
        id="post-id",
        title="Migrated post",
        status="published",
        published_at=None,
        url="https://site.example/music/migrated-post/",
        feature_image=None,
        slug="migrated-post",
        html=None,
    )
    seen = {}

    class FakeContentClient:
        def get_post_by_slug(self, slug):
            seen["slug"] = slug
            return content_post

    class FakeAdminClient:
        def get_post(self, post_id):
            seen["get"] = post_id
            return {
                "id": post_id,
                "title": "Migrated post",
                "updated_at": "2026-08-26T12:00:00.000Z",
                "html": '<img src="https://cdn.example/photo-300x200.jpg">',
            }

        def update_post_html(self, post_id, **kwargs):
            seen["update"] = (post_id, kwargs)
            return {"id": post_id, **kwargs}

    class FakeImageClient:
        def __init__(self, **kwargs):
            seen["image_client_options"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(cli, "ghost_client", lambda: FakeContentClient())
    monkeypatch.setattr(cli, "ghost_admin_client", lambda: FakeAdminClient())
    monkeypatch.setattr(cli.httpx, "Client", FakeImageClient)
    monkeypatch.setattr(
        cli,
        "image_url_loads",
        lambda _client, url: url == "https://cdn.example/photo.jpg",
    )

    result = runner.invoke(
        cli.app,
        ["repair-post-images", "https://site.example/music/migrated-post/?utm_source=test"],
    )

    assert result.exit_code == 0, result.output
    assert "1 repaired" in result.output
    assert "Updated Ghost post: Migrated post" in result.output
    assert seen["slug"] == "migrated-post"
    assert seen["get"] == "post-id"
    post_id, update = seen["update"]
    assert post_id == "post-id"
    assert update["updated_at"] == "2026-08-26T12:00:00.000Z"
    assert update["html"] == '<img src="https://cdn.example/photo.jpg">'


def test_repair_post_images_command_does_not_save_unresolved_images(monkeypatch):
    content_post = GhostPost(
        "post-id",
        "Broken post",
        "published",
        None,
        "https://site.example/broken-post/",
        None,
        "broken-post",
        None,
    )

    class FakeContentClient:
        def get_post_by_slug(self, slug):
            return content_post

    class FakeAdminClient:
        def get_post(self, post_id):
            return {
                "updated_at": "2026-08-26T12:00:00.000Z",
                "html": '<img src="/missing-300x200.jpg">',
            }

        def update_post_html(self, *args, **kwargs):
            raise AssertionError("an unresolved post must not be updated")

    class FakeImageClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(cli, "ghost_client", lambda: FakeContentClient())
    monkeypatch.setattr(cli, "ghost_admin_client", lambda: FakeAdminClient())
    monkeypatch.setattr(cli.httpx, "Client", FakeImageClient)
    monkeypatch.setattr(cli, "image_url_loads", lambda _client, url: False)

    result = runner.invoke(
        cli.app,
        ["repair-post-images", "https://site.example/broken-post/"],
    )

    assert result.exit_code == 1
    assert "1 still broken" in result.output
    assert "the post was not updated" in result.output

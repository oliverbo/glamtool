from pathlib import Path

import pytest

from glamtool.publisher import PublishingError, prepare_post


def test_prepare_post_expands_content_blocks_metadata_and_images(tmp_path):
    (tmp_path / "cover photo.png").write_bytes(b"cover")
    (tmp_path / "inside image.png").write_bytes(b"inside")
    (tmp_path / "section.md").write_text("Hello, [%audience]!", encoding="utf-8")
    (tmp_path / "Balance Sheet.csv").write_text("Name,Score\nAda,10\n", encoding="utf-8")
    (tmp_path / "example.py").write_text("print('hello')\n", encoding="utf-8")
    source = tmp_path / "post.md"
    source.write_text(
        """---
tags:
  - News
  - Music
authors: editor@example.com
audience: readers
---
# A **Prepared** Post

![Cover](cover%20photo.png)

/section.md
Audience: friends

/Balance Sheet.csv

/example.py

/inside image.png "Ignored caption"
Alt: Inside image
""",
        encoding="utf-8",
    )

    post = prepare_post(source)

    assert post.title == "A Prepared Post"
    assert post.tags == ["News", "Music"]
    assert post.authors == ["editor@example.com"]
    assert [image.source for image in post.images] == [
        (tmp_path / "cover photo.png").resolve(),
        (tmp_path / "inside image.png").resolve(),
    ]
    assert post.feature_image == post.images[0]
    assert post.images[1].alt == "Inside image"

    html = post.render_html(
        {
            post.images[0].placeholder: "https://ghost.example/cover.png",
            post.images[1].placeholder: "https://ghost.example/inside.png",
        }
    )
    assert "A Prepared Post" not in html
    assert "cover.png" not in html
    assert "Hello, friends!" in html
    assert "<table>" in html
    assert "<code class=\"language-py\">" in html
    assert 'src="https://ghost.example/inside.png"' in html


def test_nested_content_block_images_are_resolved_from_the_included_file(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    (parts / "photo.jpg").write_bytes(b"image")
    (parts / "section.md").write_text("![Nested](photo.jpg)", encoding="utf-8")
    source = tmp_path / "post.md"
    source.write_text("# Title\n\n/parts/section.md\n", encoding="utf-8")

    post = prepare_post(source)

    assert post.images[0].source == (parts / "photo.jpg").resolve()


def test_bare_image_content_block_is_used_as_feature_image(tmp_path):
    image = tmp_path / "Mallory Hawk.jpg"
    image.write_bytes(b"image")
    source = tmp_path / "post.txt"
    source.write_text("# Title\n\nMallory Hawk.jpg\n\nBody\n", encoding="utf-8")

    post = prepare_post(source)

    assert [asset.source for asset in post.images] == [image.resolve()]
    assert post.feature_image == post.images[0]
    assert "Mallory Hawk.jpg" not in post.markdown


def test_bare_content_blocks_support_captions_and_text_files(tmp_path):
    image = tmp_path / "cover photo.jpg"
    image.write_bytes(b"image")
    section = tmp_path / "section.txt"
    section.write_text("Included text", encoding="utf-8")
    source = tmp_path / "post.txt"
    source.write_text(
        '# Title\n\ncover photo.jpg "Cover caption"\n\nsection.txt\n',
        encoding="utf-8",
    )

    post = prepare_post(source)

    assert post.images[0].source == image.resolve()
    assert post.images[0].alt == "Cover caption"
    assert "Included text" in post.markdown


def test_missing_bare_content_block_candidate_remains_text(tmp_path):
    source = tmp_path / "post.txt"
    source.write_text("# Title\n\nNotes.txt\n", encoding="utf-8")

    post = prepare_post(source)

    assert post.images == []
    assert post.markdown == "Notes.txt"


def test_missing_explicit_content_block_is_still_rejected(tmp_path):
    source = tmp_path / "post.txt"
    source.write_text("# Title\n\n/missing.txt\n", encoding="utf-8")

    with pytest.raises(PublishingError, match="Referenced file does not exist"):
        prepare_post(source)


def test_recursive_content_blocks_are_rejected(tmp_path):
    (tmp_path / "a.md").write_text("/b.md\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("/a.md\n", encoding="utf-8")
    source = tmp_path / "post.md"
    source.write_text("# Title\n\n/a.md\n", encoding="utf-8")

    with pytest.raises(PublishingError, match="Recursive content block"):
        prepare_post(source)


def test_content_blocks_cannot_escape_document_folder(tmp_path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("Outside", encoding="utf-8")
    source = tmp_path / "post.md"
    source.write_text("# Title\n\n/../outside.md\n", encoding="utf-8")

    try:
        with pytest.raises(PublishingError, match="escapes the document folder"):
            prepare_post(source)
    finally:
        outside.unlink()


def test_a_heading_is_required(tmp_path):
    source = tmp_path / "post.md"
    source.write_text("Body only\n", encoding="utf-8")

    with pytest.raises(PublishingError, match="must contain a heading"):
        prepare_post(source)


def test_content_block_and_image_syntax_inside_code_fences_is_left_alone(tmp_path):
    source = tmp_path / "post.md"
    source.write_text(
        "# Title\n\n```markdown\n/missing.md\n![Example](missing.png)\n```\n",
        encoding="utf-8",
    )

    post = prepare_post(source)

    assert post.images == []
    assert "/missing.md" in post.markdown
    assert "![Example](missing.png)" in post.markdown

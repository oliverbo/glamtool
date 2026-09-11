from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape, unescape
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlparse

from writer_md import (
    WriterMdError,
    create_renderer,
    expand_content_blocks,
    metadata_list,
    normalize_metadata,
    render,
    split_front_matter,
    strip_annotations,
    substitute_variables,
)


class PublishingError(ValueError):
    """Raised when a source document cannot be prepared for publishing."""


IMAGE_RE = re.compile(
    r"!\[(?P<alt>(?:\\.|[^\]\\])*)\]\("
    r"(?P<destination><[^>]+>|[^\s)]+)"
    r"(?:\s+(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|\((?P<paren>[^)]*)\)))?\)"
)
FENCE_RE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})")
_MARKDOWN_RENDERER = create_renderer()


@dataclass(frozen=True)
class ImageAsset:
    placeholder: str
    source: Path | str
    alt: str = ""
    caption: str = ""

    @property
    def is_local(self) -> bool:
        return isinstance(self.source, Path)


@dataclass(frozen=True)
class PreparedPost:
    title: str
    markdown: str
    tags: list[str]
    authors: list[str]
    images: list[ImageAsset]

    @property
    def feature_image(self) -> ImageAsset | None:
        return self.images[0] if self.images else None

    def render_html(self, image_urls: Mapping[str, str]) -> str:
        rendered = render(self.markdown, renderer=_MARKDOWN_RENDERER)
        for image in self.images:
            if image.placeholder in rendered:
                try:
                    url = image_urls[image.placeholder]
                except KeyError as exc:
                    raise PublishingError(f"Missing uploaded URL for {image.source}") from exc
                rendered = rendered.replace(image.placeholder, escape(url, quote=True))
        return rendered.strip()


def markdown_renderer():
    return create_renderer()


def prepare_post(source: Path) -> PreparedPost:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise PublishingError(f"Markdown file does not exist: {source}")

    root = source.parent
    text = strip_annotations(source.read_text(encoding="utf-8"))
    try:
        metadata, body = split_front_matter(text, source=source)
        normalized_metadata = normalize_metadata(metadata)
        expanded = expand_content_blocks(
            body,
            current_file=source,
            root=root,
            metadata=normalized_metadata,
            stack=(source,),
        )
        expanded = substitute_variables(expanded, normalized_metadata)
        tags = metadata_list(metadata, "tags")
        authors = metadata_list(metadata, "authors")
    except WriterMdError as exc:
        raise PublishingError(str(exc)) from exc

    title, body_without_title = _extract_title(expanded)
    markdown, images = _extract_images(body_without_title, source, root)

    return PreparedPost(
        title=title,
        markdown=markdown.strip(),
        tags=tags,
        authors=authors,
        images=images,
    )


def _safe_child_path(base: Path, relative: Path, root: Path) -> Path:
    if relative.is_absolute():
        raise PublishingError(f"Absolute referenced paths are not allowed: {relative}")
    path = (base / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PublishingError(f"Referenced file escapes the document folder: {relative}") from exc
    if not path.is_file():
        raise PublishingError(f"Referenced file does not exist: {relative}")
    return path


def _extract_title(markdown: str) -> tuple[str, str]:
    tokens = _MARKDOWN_RENDERER.parse(markdown)
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        inline = tokens[index + 1]
        title = "".join(
            child.content if child.type not in {"softbreak", "hardbreak"} else " "
            for child in (inline.children or [])
            if child.type in {"text", "code_inline", "softbreak", "hardbreak"}
        ).strip()
        if not title:
            raise PublishingError("The first heading must contain a title")
        lines = markdown.splitlines()
        del lines[token.map[0] : token.map[1]]
        return title, "\n".join(lines)
    raise PublishingError("The Markdown document must contain a heading for the post title")


def _extract_images(markdown: str, source: Path, root: Path) -> tuple[str, list[ImageAsset]]:
    images: list[ImageAsset] = []
    first = True
    fence: tuple[str, int] | None = None
    standalone_image = False

    def replace(match: re.Match[str]) -> str:
        nonlocal first
        raw_destination = match.group("destination")
        destination = raw_destination[1:-1] if raw_destination.startswith("<") else raw_destination
        parsed = urlparse(destination)
        if parsed.scheme in {"http", "https"} or destination.startswith("//"):
            image_source: Path | str = destination
        elif parsed.scheme:
            raise PublishingError(f"Unsupported image URL in {source}: {destination}")
        else:
            image_source = _safe_child_path(source.parent, Path(unquote(destination)), root)

        placeholder = f"glamtool-image-{len(images)}.invalid"
        caption = (
            match.group("double") or match.group("single") or match.group("paren") or ""
        )
        asset = ImageAsset(
            placeholder=placeholder,
            source=image_source,
            alt=unescape(match.group("alt").replace("\\]", "]").replace("\\\\", "\\")),
            caption=unescape(caption),
        )
        images.append(asset)
        if first:
            first = False
            return ""
        if asset.caption and standalone_image:
            return (
                '<figure class="kg-card kg-image-card kg-card-hascaption">\n'
                f'<img src="{placeholder}" class="kg-image" alt="{escape(asset.alt, quote=True)}">\n'
                f"<figcaption>{escape(asset.caption)}</figcaption>\n"
                "</figure>"
            )
        return match.group(0).replace(raw_destination, placeholder, 1)

    output: list[str] = []
    for line in markdown.splitlines():
        marker = FENCE_RE.match(line)
        if marker:
            value = marker.group("marker")
            if fence is None:
                fence = (value[0], len(value))
            elif value[0] == fence[0] and len(value) >= fence[1]:
                fence = None
            output.append(line)
        elif fence is None:
            standalone_image = IMAGE_RE.fullmatch(line.strip()) is not None
            output.append(IMAGE_RE.sub(replace, line))
        else:
            output.append(line)
    return "\n".join(output), images

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

import yaml
from markdown_it import MarkdownIt


class PublishingError(ValueError):
    """Raised when a source document cannot be prepared for publishing."""


IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".text"}
CONTENT_BLOCK_RE = re.compile(
    r"^/(?P<path>.+?\.[A-Za-z0-9]+)"
    r"(?:\s+(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|\((?P<paren>[^)]*)\)))?\s*$"
)
METADATA_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]*\s*:")
VARIABLE_RE = re.compile(r"\[%([A-Za-z][A-Za-z0-9 _-]*)\]")
IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\("
    r"(?P<destination><[^>]+>|[^\s)]+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\)"
)
FENCE_RE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})")


@dataclass(frozen=True)
class ImageAsset:
    placeholder: str
    source: Path | str
    alt: str = ""

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
        markdown = self.markdown
        for image in self.images:
            if image.placeholder in markdown:
                try:
                    url = image_urls[image.placeholder]
                except KeyError as exc:
                    raise PublishingError(f"Missing uploaded URL for {image.source}") from exc
                markdown = markdown.replace(image.placeholder, url)
        return markdown_renderer().render(markdown).strip()


def markdown_renderer() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])


def prepare_post(source: Path) -> PreparedPost:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise PublishingError(f"Markdown file does not exist: {source}")

    root = source.parent
    text = source.read_text(encoding="utf-8")
    metadata, body = _split_front_matter(text, source)
    expanded = _expand_content(
        body,
        current_file=source,
        root=root,
        metadata=_normalize_metadata(metadata),
        stack=(source,),
    )
    expanded = _substitute_variables(expanded, _normalize_metadata(metadata))
    title, body_without_title = _extract_title(expanded)
    markdown, images = _extract_images(body_without_title, source, root)

    return PreparedPost(
        title=title,
        markdown=markdown.strip(),
        tags=_metadata_list(metadata, "tags"),
        authors=_metadata_list(metadata, "authors"),
        images=images,
    )


def _split_front_matter(text: str, source: Path) -> tuple[dict[str, Any], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text

    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if closing is None:
        raise PublishingError(f"Unclosed front matter in {source}")

    raw = "".join(lines[1:closing])
    try:
        parsed = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise PublishingError(f"Invalid front matter in {source}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PublishingError(f"Front matter in {source} must be a mapping")
    return {str(key): value for key, value in parsed.items()}, "".join(lines[closing + 1 :])


def _normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key).strip().lower(): value for key, value in metadata.items()}


def _metadata_list(metadata: Mapping[str, Any], key: str) -> list[str]:
    normalized = _normalize_metadata(metadata)
    value = normalized.get(key)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result = [str(item).strip() for item in values if str(item).strip()]
    if any(isinstance(item, (dict, list)) for item in values):
        raise PublishingError(f"Front matter '{key}' must be a string or list of strings")
    return result


def _expand_content(
    text: str,
    *,
    current_file: Path,
    root: Path,
    metadata: Mapping[str, Any],
    stack: tuple[Path, ...],
) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    fence: tuple[str, int] | None = None

    while index < len(lines):
        marker = FENCE_RE.match(lines[index])
        if marker:
            value = marker.group("marker")
            if fence is None:
                fence = (value[0], len(value))
            elif value[0] == fence[0] and len(value) >= fence[1]:
                fence = None
            output.append(lines[index])
            index += 1
            continue
        if fence is not None:
            output.append(lines[index])
            index += 1
            continue

        match = CONTENT_BLOCK_RE.match(lines[index])
        if not match:
            output.append(_rebase_image_destinations(lines[index], current_file, root))
            index += 1
            continue

        block_metadata, next_index = _consume_block_metadata(lines, index + 1, current_file)
        merged_metadata = {**_normalize_metadata(metadata), **_normalize_metadata(block_metadata)}
        relative = Path(unquote(match.group("path").strip()))
        block_path = _safe_child_path(current_file.parent, relative, root)
        caption = (
            str(_normalize_metadata(block_metadata).get("alt", "")).strip()
            or match.group("double")
            or match.group("single")
            or match.group("paren")
            or ""
        )
        output.append(
            _render_content_block(
                block_path,
                caption=caption,
                root=root,
                metadata=merged_metadata,
                stack=stack,
            )
        )
        index = next_index

    return "\n".join(output)


def _consume_block_metadata(
    lines: list[str], index: int, source: Path
) -> tuple[dict[str, Any], int]:
    if index >= len(lines):
        return {}, index

    if lines[index].strip() == "---":
        closing = next(
            (position for position in range(index + 1, len(lines)) if lines[position].strip() == "---"),
            None,
        )
        if closing is None:
            raise PublishingError(f"Unclosed content block metadata in {source}")
        raw = "\n".join(lines[index + 1 : closing])
        return _load_block_metadata(raw, source), closing + 1

    end = index
    while end < len(lines) and METADATA_LINE_RE.match(lines[end]):
        end += 1
    if end == index:
        return {}, index
    raw = "\n".join(lines[index:end])
    return _load_block_metadata(raw, source), end


def _load_block_metadata(raw: str, source: Path) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise PublishingError(f"Invalid content block metadata in {source}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PublishingError(f"Content block metadata in {source} must be a mapping")
    return {str(key): value for key, value in parsed.items()}


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


def _render_content_block(
    path: Path,
    *,
    caption: str,
    root: Path,
    metadata: Mapping[str, Any],
    stack: tuple[Path, ...],
) -> str:
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        relative = path.relative_to(root).as_posix()
        destination = f"<{relative}>" if " " in relative else relative
        return f"![{caption}]({destination})"

    if path in stack:
        chain = " -> ".join(item.name for item in (*stack, path))
        raise PublishingError(f"Recursive content block detected: {chain}")

    if suffix == ".csv":
        return _csv_to_markdown(path)

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PublishingError(f"Content block is not UTF-8 text: {path}") from exc

    if suffix in TEXT_EXTENSIONS:
        included_metadata, included_body = _split_front_matter(content, path)
        merged = {
            **_normalize_metadata(included_metadata),
            **_normalize_metadata(metadata),
        }
        expanded = _expand_content(
            included_body,
            current_file=path,
            root=root,
            metadata=merged,
            stack=(*stack, path),
        )
        return _substitute_variables(expanded, merged)

    language = suffix.removeprefix(".") or "text"
    return f"```{language}\n{content.rstrip()}\n```"


def _csv_to_markdown(path: Path) -> str:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").strip()

    header = "| " + " | ".join(cell(value) for value in padded[0]) + " |"
    divider = "| " + " | ".join("---" for _ in range(width)) + " |"
    body = ["| " + " | ".join(cell(value) for value in row) + " |" for row in padded[1:]]
    return "\n".join([header, divider, *body])


def _substitute_variables(text: str, metadata: Mapping[str, Any]) -> str:
    normalized = _normalize_metadata(metadata)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        value = normalized.get(key)
        if value is None:
            return match.group(0)
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    return VARIABLE_RE.sub(replace, text)


def _rebase_image_destinations(line: str, source: Path, root: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_destination = match.group("destination")
        destination = raw_destination[1:-1] if raw_destination.startswith("<") else raw_destination
        parsed = urlparse(destination)
        if parsed.scheme or destination.startswith("//"):
            return match.group(0)
        path = _safe_child_path(source.parent, Path(unquote(destination)), root)
        rebased = path.relative_to(root).as_posix()
        replacement = f"<{rebased}>" if " " in rebased else rebased
        return match.group(0).replace(raw_destination, replacement, 1)

    return IMAGE_RE.sub(replace, line)


def _extract_title(markdown: str) -> tuple[str, str]:
    tokens = markdown_renderer().parse(markdown)
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
        asset = ImageAsset(placeholder=placeholder, source=image_source, alt=match.group("alt"))
        images.append(asset)
        if first:
            first = False
            return ""
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
            output.append(IMAGE_RE.sub(replace, line))
        else:
            output.append(line)
    return "\n".join(output), images

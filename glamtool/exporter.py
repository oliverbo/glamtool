from __future__ import annotations

import json
import mimetypes
import re
import shutil
from dataclasses import dataclass
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .ghost import GhostPost
from .markdown import GhostHtmlParser, HtmlNode, html_to_markdown, render_html_node


class ExportError(ValueError):
    """A complete portable post could not be exported."""


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:80] or "post"


@dataclass(frozen=True)
class ExportResult:
    path: Path
    overwritten: bool


def export_post(post: GhostPost, output: Path, client: httpx.Client) -> ExportResult:
    """Prepare a complete post before replacing any existing backup."""
    if post.html is None:
        raise ExportError("Post HTML is missing")
    folder = f"{normalize_name((post.published_at or 'undated')[:10])}-{normalize_name(post.title or post.slug or 'untitled')}"
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".glamtool-", dir=output) as temporary:
        root = Path(temporary)
        images = root / "images"
        downloaded: dict[str, str] = {}

        def download(source: str, *, feature: bool = False) -> str:
            url = urljoin(post.url or str(client.base_url), source.strip())
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ExportError(f"Unsupported image URL: {source}")
            url = urlunsplit(parsed._replace(fragment=""))
            if url in downloaded:
                return downloaded[url]
            response = client.get(url)
            response.raise_for_status()
            media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if not media_type.startswith("image/") or not response.content:
                raise ExportError(f"Image response is empty or has invalid Content-Type: {url}")
            extension = {"image/jpeg": ".jpg", "image/svg+xml": ".svg"}.get(media_type)
            extension = extension or mimetypes.guess_extension(media_type)
            if not extension or not re.fullmatch(r"\.[a-z0-9]+", extension):
                raise ExportError(f"Unsupported image type: {media_type}")
            name = "feature" if feature else f"image-{len(downloaded) + 1:03d}"
            relative = f"images/{name}{extension}"
            images.mkdir(exist_ok=True)
            (root / relative).write_bytes(response.content)
            downloaded[url] = relative
            return relative

        feature_image = download(post.feature_image, feature=True) if post.feature_image else None
        parser = GhostHtmlParser()
        parser.feed(post.html)
        parser.close()

        def localize(node: HtmlNode | str, parent_tag: str = "") -> None:
            if isinstance(node, str):
                return
            if node.tag == "img" or (node.tag == "source" and parent_tag == "picture"):
                if node.attrs.get("src"):
                    node.attrs["src"] = download(node.attrs["src"])
                # Retain all responsive variants in the archive; Markdown uses src.
                if node.attrs.get("srcset"):
                    candidates = []
                    for candidate in node.attrs["srcset"].split(","):
                        parts = candidate.strip().split()
                        if parts:
                            candidates.append((download(parts[0]), parts[1:]))
                    if node.tag == "img" and not node.attrs.get("src") and candidates:
                        node.attrs["src"] = candidates[-1][0]
                    node.attrs.pop("srcset", None)
            for child in node.children:
                localize(child, node.tag)

        localize(parser.root)
        body = render_html_node(parser.root)
        body = re.sub(r"[ \t]+\n", "\n", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        title = (post.title or "(untitled)").replace("\n", " ")
        metadata = {
            "published": post.published_at,
            "updated": post.updated_at,
            "url": post.url,
            "authors": post.authors,
            "tags": post.tags,
        }
        # JSON scalars and arrays are valid YAML and safely quote arbitrary names.
        front_matter = "---\n" + "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in metadata.items()
        ) + "\n---"
        sections = [front_matter, f"# {title}"]
        if feature_image:
            alt = (post.feature_image_alt or "").replace("\\", "\\\\").replace("]", "\\]")
            sections.append(f"![{alt}]({feature_image})")
            if post.feature_image_caption:
                sections.append(html_to_markdown(post.feature_image_caption))
        if body:
            sections.append(body)
        (root / "post.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        (root / "images.json").write_text(
            json.dumps(downloaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        destination = output / folder
        overwritten = destination.is_dir() and not destination.is_symlink()
        if destination.exists() or destination.is_symlink():
            if not overwritten:
                raise ExportError(f"Export destination is not a directory: {destination}")
            shutil.rmtree(destination)
        root.rename(destination)
    return ExportResult(destination, overwritten)

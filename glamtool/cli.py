from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import typer
from rich.console import Console
from rich.table import Table

from .config import settings
from .ghost import GhostContentClient

app = typer.Typer(add_completion=False, help="Maintenance utilities for Ghost + APIs.")
console = Console()
MARKDOWN_POST_FIELDS = "id,title,status,published_at,url,slug,html"


class MarkdownFormat(str, Enum):
    post = "post"
    header = "header"


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["HtmlNode | str"] = field(default_factory=list)


class GhostHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        node = HtmlNode(tag.lower(), {k.lower(): v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if node.tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "track",
            "wbr",
        }:
            self.stack.append(node)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag:
                del self.stack[idx:]
                break

    def handle_data(self, data: str):
        self.stack[-1].children.append(data)


def ghost_client() -> GhostContentClient:
    return GhostContentClient(settings.ghost_url, settings.ghost_content_key)


def build_filter(
    published_only: bool,
    missing_images_only: bool,
    tags: Optional[list[str]],
    any_tag: bool,
    raw_filter: Optional[str],
) -> Optional[str]:
    """
    Build a Ghost Content API filter string.
    We combine pieces with '+' (AND).
    Tag filtering:
      - default is AND across tags: tag:foo+tag:bar
      - with --any-tag: tag:[foo,bar]
    """
    parts: list[str] = []

    if published_only:
        parts.append("status:published")
    if missing_images_only:
        parts.append("feature_image:null")

    if tags:
        cleaned = [t.strip() for t in tags if t.strip()]
        if cleaned:
            if any_tag and len(cleaned) > 1:
                # OR across tags
                parts.append(f"tag:[{','.join(cleaned)}]")
            else:
                # AND across tags
                parts.extend([f"tag:{t}" for t in cleaned])

    if raw_filter:
        # Allow advanced users to add anything (will still be AND'ed with other parts)
        parts.append(raw_filter.strip())

    return "+".join([p for p in parts if p]) or None


def parse_date_option(value: Optional[str], option_name: str) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"{option_name} must use YYYY-MM-DD format")


def build_published_at_filter(
    start_date: Optional[str],
    end_date: Optional[str],
    week: Optional[str],
) -> Optional[str]:
    if week and (start_date or end_date):
        raise typer.BadParameter("--week cannot be combined with --start-date or --end-date")

    start = parse_date_option(start_date, "--start-date")
    end = parse_date_option(end_date, "--end-date")

    if week:
        week_date = parse_date_option(week, "--week")
        if week_date is not None:
            start = week_date
            end = start + timedelta(days=6)

    if start and end and start > end:
        raise typer.BadParameter("--start-date cannot be after --end-date")

    parts: list[str] = []
    if start:
        parts.append(f"published_at:>='{start.isoformat()}'")
    if end:
        exclusive_end = end + timedelta(days=1)
        parts.append(f"published_at:<'{exclusive_end.isoformat()}'")
    return "+".join(parts) or None


def combine_filters(*filters: Optional[str]) -> Optional[str]:
    parts = [filter_.strip() for filter_ in filters if filter_ and filter_.strip()]
    return "+".join(parts) or None


def normalize_youtube_url(src: str) -> str:
    parsed = urlparse(src)
    host = parsed.netloc.lower()
    if host.endswith("youtube.com") and parsed.path.startswith("/embed/"):
        video_id = parsed.path.removeprefix("/embed/").split("/")[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    if host.endswith("youtube.com") and parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
        if video_id:
            return f"https://youtu.be/{video_id}"
    return src


def html_to_markdown(html: Optional[str]) -> str:
    if not html:
        return ""
    parser = GhostHtmlParser()
    parser.feed(html)
    parser.close()
    markdown = render_html_node(parser.root)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = "\n".join(line.strip() for line in markdown.splitlines())
    return markdown.strip()


def render_html_children(node: HtmlNode) -> str:
    return "".join(render_html_node(child) for child in node.children)


def render_html_node(node: HtmlNode | str) -> str:
    if isinstance(node, str):
        return node

    tag = node.tag
    content = render_html_children(node)

    if tag in {"root", "html", "body", "article", "section"}:
        return content
    if tag in {"p", "div", "figure"}:
        return f"{content.strip()}\n\n" if content.strip() else ""
    if tag in {"strong", "b"}:
        return f"**{content.strip()}**"
    if tag in {"em", "i"}:
        return f"*{content.strip()}*"
    if tag == "br":
        return "\n"
    if tag == "hr":
        return "\n---\n\n"
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        level = int(tag[1])
        return f"{'#' * level} {content.strip()}\n\n"
    if tag == "blockquote":
        lines = content.strip().splitlines()
        quoted = "\n".join(f"> {line.strip()}" if line.strip() else ">" for line in lines)
        return f"{quoted}\n\n" if quoted else ""
    if tag == "a":
        href = node.attrs.get("href", "").strip()
        label = content.strip() or href
        return f"[{label}]({href})" if href else label
    if tag in {"iframe", "embed"}:
        src = node.attrs.get("src", "").strip()
        return f"\n{normalize_youtube_url(src)}\n\n" if src else ""
    if tag == "img":
        src = node.attrs.get("src", "").strip()
        alt = node.attrs.get("alt", "").strip()
        return f"![{alt}]({src})" if src else alt
    if tag in {"ul", "ol"}:
        ordered = tag == "ol"
        items = [child for child in node.children if isinstance(child, HtmlNode) and child.tag == "li"]
        lines = []
        for index, item in enumerate(items, start=1):
            bullet = f"{index}." if ordered else "-"
            lines.append(f"{bullet} {render_html_children(item).strip()}")
        return "\n".join(lines) + ("\n\n" if lines else "")
    if tag == "li":
        return content
    if tag in {"script", "style"}:
        return ""
    return content


def render_markdown_posts(posts, format_: MarkdownFormat) -> str:
    blocks: list[str] = []
    for post in posts:
        title = post.title or "(untitled)"
        if format_ == MarkdownFormat.header:
            url = post.url or ""
            blocks.append(f"- [{title}]({url})" if url else f"- {title}")
        else:
            body = html_to_markdown(post.html)
            blocks.append(f"## {title}\n\n{body}".rstrip())
    separator = "\n" if format_ == MarkdownFormat.header else "\n\n"
    return separator.join(blocks).strip() + ("\n" if blocks else "")


@app.command()
def posts(
    limit: int = typer.Option(15, help="Number of posts to show (max 100)."),
    published_only: bool = typer.Option(True, help="Show only published posts."),
    missing_images_only: bool = typer.Option(False, help="Only posts without feature_image."),
    tag: Optional[list[str]] = typer.Option(
        None,
        "--tag",
        help="Filter by tag (repeatable). Example: --tag song-pick --tag 2026",
    ),
    any_tag: bool = typer.Option(
        False, help="If multiple --tag are given, match ANY of them (OR) instead of ALL (AND)."
    ),
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        help="Raw Ghost filter expression to AND with other options. Example: 'title:~\"Olympics\"'",
    ),
):
    """
    List Ghost posts with powerful filtering (tags, raw filter, etc.).
    """
    client = ghost_client()

    filter_ = build_filter(
        published_only=published_only,
        missing_images_only=missing_images_only,
        tags=tag,
        any_tag=any_tag,
        raw_filter=filter,
    )

    items = client.list_posts(limit=limit, filter_=filter_)

    table = Table(title=f"Ghost Posts{f'  (filter: {filter_})' if filter_ else ''}")
    table.add_column("Title", overflow="fold")
    table.add_column("Status", style="dim")
    table.add_column("Published", style="dim")
    table.add_column("Has Image?", justify="center")
    table.add_column("URL", overflow="fold")

    for p in items:
        table.add_row(
            p.title or "(untitled)",
            p.status or "",
            (p.published_at or "")[:10],
            "✅" if p.feature_image else "—",
            p.url or "",
        )

    console.print(table)


@app.command()
def export_posts(
    out: Path = typer.Option(Path("posts_export.csv"), help="CSV output path."),
    published_only: bool = typer.Option(True, help="Export only published posts."),
    tag: Optional[list[str]] = typer.Option(
        None,
        "--tag",
        help="Filter by tag (repeatable). Example: --tag song-pick --tag 2026",
    ),
    any_tag: bool = typer.Option(
        False, help="If multiple --tag are given, match ANY of them (OR) instead of ALL (AND)."
    ),
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        help="Raw Ghost filter expression to AND with other options.",
    ),
):
    """
    Export posts to CSV with the same filtering options as 'posts'.
    """
    client = ghost_client()

    filter_ = build_filter(
        published_only=published_only,
        missing_images_only=False,
        tags=tag,
        any_tag=any_tag,
        raw_filter=filter,
    )

    posts = client.paginate_posts(filter_=filter_)

    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "status", "published_at", "url", "feature_image", "slug"])
        for p in posts:
            w.writerow([p.id, p.title, p.status, p.published_at, p.url, p.feature_image, p.slug])

    console.print(f"✅ Exported {len(posts)} posts to {out}")
    if filter_:
        console.print(f"[dim]Filter used:[/dim] {filter_}")


@app.command()
def export_markdown(
    out: Optional[Path] = typer.Option(
        None,
        "--out",
        help="Markdown output path. If omitted, Markdown is printed to stdout.",
    ),
    format_: MarkdownFormat = typer.Option(
        MarkdownFormat.post,
        "--format",
        help='Markdown output format: "post" for full posts or "header" for linked titles.',
    ),
    published_only: bool = typer.Option(True, help="Export only published posts."),
    tag: Optional[list[str]] = typer.Option(
        None,
        "--tag",
        help="Filter by tag (repeatable). Example: --tag song-pick --tag 2026",
    ),
    any_tag: bool = typer.Option(
        False, help="If multiple --tag are given, match ANY of them (OR) instead of ALL (AND)."
    ),
    filter: Optional[str] = typer.Option(
        None,
        "--filter",
        help="Raw Ghost filter expression to AND with other options.",
    ),
    start_date: Optional[str] = typer.Option(
        None,
        "--start-date",
        help="Only include posts published on or after this date (YYYY-MM-DD).",
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="Only include posts published on or before this date (YYYY-MM-DD).",
    ),
    week: Optional[str] = typer.Option(
        None,
        "--week",
        help="Shortcut for seven days starting with this date (YYYY-MM-DD).",
    ),
):
    """
    Export posts as Markdown, including full Ghost post bodies or linked title headers.
    """
    client = ghost_client()

    base_filter = build_filter(
        published_only=published_only,
        missing_images_only=False,
        tags=tag,
        any_tag=any_tag,
        raw_filter=filter,
    )
    date_filter = build_published_at_filter(start_date=start_date, end_date=end_date, week=week)
    filter_ = combine_filters(base_filter, date_filter)

    posts = client.paginate_posts(
        filter_=filter_,
        fields=MARKDOWN_POST_FIELDS,
        order="published_at asc",
    )
    markdown = render_markdown_posts(posts, format_)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        console.print(f"Exported {len(posts)} posts to {out}")
        if filter_:
            console.print(f"[dim]Filter used:[/dim] {filter_}")
        return

    console.out(markdown, end="")


@app.command()
def sanity():
    """
    Quick config + connectivity check.
    """
    client = ghost_client()
    try:
        items = client.list_posts(limit=1)
    except Exception as e:
        console.print(f"[red]❌ Ghost API call failed:[/red] {e}")
        raise typer.Exit(code=1)

    console.print("[green]✅ Ghost API call works.[/green]")
    if items:
        console.print(f"Latest: [bold]{items[0].title}[/bold]")


def main():
    app()


if __name__ == "__main__":
    main()

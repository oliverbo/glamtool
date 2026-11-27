from __future__ import annotations

import csv
import re
from datetime import date, timedelta
from enum import Enum
from html import escape as escape_html
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx
import typer
from rich.console import Console
from rich.table import Table

from .markdown import html_to_markdown
from .exporter import ExportError, export_post
from .config import settings
from .glamglare import GlamglareApiError, GlamglareArtist, GlamglareClient
from .ghost import GhostAdminClient, GhostContentClient
from .image_repair import ImageRepairError, image_url_loads, repair_embedded_images
from .publisher import PublishingError, prepare_post

app = typer.Typer(add_completion=False, help="Maintenance utilities for Ghost + APIs.")
console = Console()
error_console = Console(stderr=True)
MARKDOWN_POST_FIELDS = "id,title,status,published_at,url,slug,html"


class MarkdownFormat(str, Enum):
    post = "post"
    header = "header"
    instagram = "instagram"


class InstagramRollCallError(ValueError):
    """Raised when one or more Song Picks cannot be rendered as a roll call."""



def ghost_client() -> GhostContentClient:
    return GhostContentClient(settings.ghost_url, settings.ghost_content_key)


def ghost_admin_client() -> GhostAdminClient:
    if not settings.ghost_admin_key:
        raise PublishingError(
            "GHOST_ADMIN_KEY is required for modifying Ghost posts; "
            "create a Custom Integration in Ghost Admin"
        )
    return GhostAdminClient(settings.ghost_url, settings.ghost_admin_key)


def glamglare_client() -> GlamglareClient:
    if (
        not settings.gg_api_url
        or not settings.gg_api_url.strip()
        or not settings.gg_api_secret
        or not settings.gg_api_secret.strip()
    ):
        raise InstagramRollCallError(
            "GG_API_URL and GG_API_SECRET are required for Instagram roll-call exports"
        )
    return GlamglareClient(settings.gg_api_url, settings.gg_api_secret)


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


def parse_song_pick_title(title: str) -> tuple[str, str]:
    value = title.strip()
    value = re.sub(r"^Song Pick:\s*", "", value, flags=re.IGNORECASE)
    match = re.match(r"^(?P<artist>.+?)\s+-\s+(?P<song>.+)$", value)
    if not match:
        raise ValueError("expected 'Artist - Song' (optionally prefixed by 'Song Pick:')")
    return match.group("artist").strip(), match.group("song").strip()


def render_instagram_roll_call(posts, client: GlamglareClient) -> str:
    lines: list[str] = []
    errors: list[str] = []
    artists: dict[str, GlamglareArtist | None] = {}

    for post in posts:
        title = post.title or ""
        try:
            artist_name, song_name = parse_song_pick_title(title)
        except ValueError as exc:
            errors.append(f"{title or '(untitled)'}: {exc}")
            continue

        cache_key = artist_name.casefold()
        if cache_key not in artists:
            artists[cache_key] = client.find_artist(artist_name)
        artist = artists[cache_key]
        if artist is None:
            errors.append(f"{title}: artist {artist_name!r} was not found")
            continue
        handle = (artist.instagram_handle or "").lstrip("@").strip()
        artist_label = f"@{handle}" if handle else artist.name
        lines.append(f"- {artist_label} - {song_name}")

    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise InstagramRollCallError(f"Could not resolve all Song Picks:\n{details}")
    return "\n".join(lines) + ("\n" if lines else "")


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
        help=(
            'Markdown output format: "post" for full posts, "header" for linked titles, '
            'or "instagram" for an Instagram roll call.'
        ),
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
    Export posts as Markdown, including full posts, linked titles, or an Instagram roll call.
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
    try:
        if format_ == MarkdownFormat.instagram:
            markdown = render_instagram_roll_call(posts, glamglare_client())
        else:
            markdown = render_markdown_posts(posts, format_)
    except (GlamglareApiError, InstagramRollCallError, httpx.HTTPError) as exc:
        error_console.print(f"[red]Could not generate Instagram roll call:[/red] {exc}")
        raise typer.Exit(code=1)

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        console.print(f"Exported {len(posts)} posts to {out}")
        if filter_:
            console.print(f"[dim]Filter used:[/dim] {filter_}")
        return

    console.out(markdown, end="")


@app.command("export-full-posts")
def export_full_posts(
    out: Path = typer.Option(Path("backups"), help="Parent directory for post folders."),
    count: int = typer.Option(1, min=1, help="Maximum number of matching posts to export."),
    start_date: Optional[str] = typer.Option(None, help="Include posts on or after YYYY-MM-DD."),
    end_date: Optional[str] = typer.Option(None, help="Include posts on or before YYYY-MM-DD."),
    week: Optional[str] = typer.Option(None, help="Seven days starting with YYYY-MM-DD."),
    tag: Optional[list[str]] = typer.Option(None, "--tag", help="Filter by tag (repeatable)."),
    any_tag: bool = typer.Option(False, help="Match any supplied tag."),
    filter: Optional[str] = typer.Option(None, "--filter", help="Additional Ghost filter."),
):
    """Back up published posts as Markdown with local images."""
    filter_ = combine_filters(
        build_filter(True, False, tag, any_tag, filter),
        build_published_at_filter(start_date, end_date, week),
    )
    try:
        items = ghost_client().paginate_posts(
            filter_=filter_, fields=MARKDOWN_POST_FIELDS + ",updated_at,feature_image,feature_image_alt,feature_image_caption",
            order="published_at asc,id asc", count=count,
            max_pages=(count + 99) // 100,
        )
    except (ValueError, httpx.HTTPError) as exc:
        error_console.print(f"Could not fetch posts: {exc}")
        raise typer.Exit(code=1)
    failed = 0
    exported = 0
    overwritten = 0
    with httpx.Client(timeout=20.0, follow_redirects=True, base_url=settings.ghost_url) as client:
        for post in items:
            try:
                result = export_post(post, out, client)
                overwritten += int(result.overwritten)
                console.print(f"Exported {post.title} to {result.path}")
                exported += 1
            except (ExportError, ValueError, OSError, httpx.HTTPError) as exc:
                failed += 1
                error_console.print(f"Could not export {post.title} ({post.id}): {exc}")
    console.print(f"Exported {exported} post(s); {overwritten} overwritten; {failed} failed.")
    if failed:
        raise typer.Exit(code=1)


@app.command("publish")
def publish_markdown(
    source: Path = typer.Argument(..., help="Markdown file to publish as a Ghost draft."),
):
    """Create a Ghost draft from an iA Writer-style Markdown document."""
    try:
        prepared = prepare_post(source)
        client = ghost_admin_client()

        uploaded: dict[Path, str] = {}
        image_urls: dict[str, str] = {}
        for image in prepared.images:
            if image.is_local:
                path = image.source
                assert isinstance(path, Path)
                if path not in uploaded:
                    uploaded[path] = client.upload_image(path)
                image_urls[image.placeholder] = uploaded[path]
            else:
                image_urls[image.placeholder] = str(image.source)

        feature_image = None
        feature_image_alt = None
        feature_image_caption = None
        if prepared.feature_image:
            feature_image = image_urls[prepared.feature_image.placeholder]
            feature_image_alt = prepared.feature_image.alt or None
            feature_image_caption = (
                escape_html(prepared.feature_image.caption) or None
            )

        post = client.create_draft(
            title=prepared.title,
            html=prepared.render_html(image_urls),
            tags=prepared.tags,
            authors=prepared.authors,
            feature_image=feature_image,
            feature_image_alt=feature_image_alt,
            feature_image_caption=feature_image_caption,
        )
    except (PublishingError, ValueError, OSError, httpx.HTTPError) as exc:
        error_console.print(f"[red]Could not create Ghost draft:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]Created Ghost draft:[/green] {post.get('title', prepared.title)}")
    if post.get("id"):
        console.print(f"[dim]ID:[/dim] {post['id']}")


def _post_url_identity(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    return parsed.netloc.casefold(), parsed.path.rstrip("/") or "/"


@app.command("repair-post-images")
def repair_post_images_command(
    post_url: str = typer.Argument(..., help="Public URL of the Ghost post to repair."),
):
    """Repair broken WordPress image variants embedded in one Ghost post."""
    try:
        parsed_url = urlparse(post_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("POST_URL must be an absolute http:// or https:// URL")
        slug = unquote(parsed_url.path.rstrip("/").rsplit("/", 1)[-1])
        if not slug:
            raise ValueError("POST_URL must include a post slug")

        content_post = ghost_client().get_post_by_slug(slug)
        if not content_post.url or _post_url_identity(content_post.url) != _post_url_identity(post_url):
            raise ValueError(
                f"Ghost post {slug!r} has URL {content_post.url!r}, not the supplied URL"
            )

        admin = ghost_admin_client()
        current_post = admin.get_post(content_post.id)
        current_html = current_post.get("html")
        if current_html is None:
            raise ValueError("Ghost Admin API response did not include the post HTML")

        with httpx.Client(timeout=20.0, follow_redirects=True) as image_client:
            result = repair_embedded_images(
                current_html,
                post_url=content_post.url,
                check_url=lambda url: image_url_loads(image_client, url),
            )

        console.print(
            "Checked "
            f"{result.checked} image(s): {result.repaired} repaired, "
            f"{result.skipped} unchanged, {result.broken} still broken."
        )
        if result.broken:
            raise ImageRepairError(
                "One or more images have no verified working source; the post was not updated"
            )
        if not result.repaired:
            console.print("[green]No update needed.[/green]")
            return

        admin.update_post_html(
            content_post.id,
            html=result.html,
            updated_at=current_post.get("updated_at", ""),
        )
    except (ImageRepairError, PublishingError, ValueError, httpx.HTTPError) as exc:
        error_console.print(f"[red]Could not repair post images:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        f"[green]Updated Ghost post:[/green] {current_post.get('title', content_post.title)}"
    )


@app.command()
def sanity():
    """
    Quick config + connectivity check.
    """
    client = ghost_client()
    try:
        items = client.list_posts(limit=1)
    except Exception as e:
        error_console.print(f"[red]❌ Ghost API call failed:[/red] {e}")
        raise typer.Exit(code=1)

    console.print("[green]✅ Ghost API call works.[/green]")
    if items:
        console.print(f"Latest: [bold]{items[0].title}[/bold]")


def main():
    app()


if __name__ == "__main__":
    main()

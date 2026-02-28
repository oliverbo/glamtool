from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .ghost import GhostContentClient

app = typer.Typer(add_completion=False, help="Maintenance utilities for Ghost + APIs.")
console = Console()
SONG_SEPARATOR_RE = re.compile(r"(?:\s+[-–—]\s*|\s*[-–—]\s+)")
SONG_TITLE_RE = re.compile(r"^\s*(?P<artist>.+?)(?:\s+[-–—]\s*|\s*[-–—]\s+)(?P<song>.+?)\s*$")


def resolve_settings(ctx: typer.Context):
    env_file = None
    if ctx.obj:
        env_file = ctx.obj.get("env_file")
    try:
        return load_settings(env_file=env_file)
    except ValidationError:
        console.print(
            "[red]❌ Missing configuration.[/red] "
            "Set `GHOST_URL` and `GHOST_CONTENT_KEY` as environment variables. "
            "Or pass `--env-file /path/to/.env`."
        )
        raise typer.Exit(code=2)


def ghost_client(ctx: typer.Context) -> GhostContentClient:
    settings = resolve_settings(ctx)
    return GhostContentClient(settings.ghost_url, settings.ghost_content_key)


@app.callback()
def app_options(
    ctx: typer.Context,
    env_file: Optional[Path] = typer.Option(
        None,
        "--env-file",
        help="Optional path to a .env file. By default, only environment variables are used.",
    ),
):
    ctx.obj = {"env_file": env_file}


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


def format_datetime_for_sheet(value: Optional[str]) -> Optional[str]:
    """
    Convert ISO-8601 timestamps from Ghost into a spreadsheet-friendly datetime string.
    """
    if not value:
        return value

    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"

    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        # Keep original value if it isn't parseable.
        return value

    return dt.strftime("%Y-%m-%d %H:%M:%S")


def extract_artist_song(title: str) -> tuple[str, str]:
    """
    Try to parse "Artist - Song" from post titles.
    Supported extras:
      - optional prefix ending with ":" before the artist/song section
      - optional trailing bracket suffix, e.g. "[VIDEO]"
    """
    if not title:
        return "", ""

    # Normalize common invisible/non-breaking whitespace that appears in copied titles.
    cleaned = title.replace("\u00A0", " ")
    cleaned = re.sub(r"[\u200B-\u200D\uFEFF]", "", cleaned)
    cleaned = re.sub(r"\s*\[[^\]]+\]\s*$", "", cleaned).strip()
    if not cleaned:
        return "", ""

    # If a prefix exists before the song separator, drop it (e.g. "SONG PICK: ").
    sep_match = SONG_SEPARATOR_RE.search(cleaned)
    if sep_match:
        colon_idx = cleaned.find(":")
        if 0 <= colon_idx < sep_match.start():
            cleaned = cleaned[colon_idx + 1 :].strip()

    match = SONG_TITLE_RE.match(cleaned)
    if not match:
        return "", ""

    artist = match.group("artist").strip()
    song = match.group("song").strip()
    if not artist or not song:
        return "", ""
    return artist, song


@app.command()
def posts(
    ctx: typer.Context,
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
    client = ghost_client(ctx)

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
    ctx: typer.Context,
    out: Path = typer.Option(Path("posts_export.csv"), help="CSV output path."),
    smart: bool = typer.Option(
        False,
        "--smart",
        help=(
            "Enable spreadsheet-friendly export: normalize published date and "
            "add parsed artist/song_title columns when detectable."
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
):
    """
    Export posts to CSV with the same filtering options as 'posts'.
    """
    client = ghost_client(ctx)

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
        base_header = ["id", "title", "published_at", "url", "feature_image", "slug"]
        if smart:
            w.writerow(base_header + ["artist", "song_title"])
        else:
            w.writerow(base_header)
        for p in posts:
            published_at = format_datetime_for_sheet(p.published_at) if smart else p.published_at
            row = [p.id, p.title, published_at, p.url, p.feature_image, p.slug]
            if smart:
                artist, song_title = extract_artist_song(p.title or "")
                row.extend([artist, song_title])
            w.writerow(row)

    console.print(f"✅ Exported {len(posts)} posts to {out}")
    if filter_:
        console.print(f"[dim]Filter used:[/dim] {filter_}")


@app.command()
def sanity(ctx: typer.Context):
    """
    Quick config + connectivity check.
    """
    client = ghost_client(ctx)
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

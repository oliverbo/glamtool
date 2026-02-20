from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import settings
from .ghost import GhostContentClient

app = typer.Typer(add_completion=False, help="Maintenance utilities for Ghost + APIs.")
console = Console()


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
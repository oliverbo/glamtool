# glamtool

`glamtool` is a small command-line utility for working with the Ghost Content API and related editorial automation tasks.

It is designed for:

- Maintenance workflows
- Exporting and filtering posts
- Tag-based queries
- Sanity checks
- Future AI-assisted editorial tooling

The goal is to provide a clean, scriptable foundation for automation without turning into a full framework.

---

## Features

- List posts from Ghost
- Filter by tags
- Combine structured filters with raw Ghost filter expressions
- Export posts to CSV
- Export posts to Markdown
- Sanity check API connectivity
- Clean CLI built with Typer
- Pretty terminal output via Rich
- Configuration via `.env`

---

## Requirements

- macOS (tested)
- Python 3.11+
- `uv` (recommended) or `venv`

Install `uv`:

```bash
brew install uv
```

---

## Setup

Clone or create the project directory, then:

```bash
uv init
uv venv
source .venv/bin/activate
uv add typer rich httpx pydantic-settings python-dotenv
```

Create a `.env` file:

```env
GHOST_URL="https://your-site.com"
GHOST_CONTENT_KEY="YOUR_CONTENT_API_KEY"
```

You can generate a Content API key in Ghost Admin under:

Settings → Integrations → Custom Integration

---

## Running Commands

From the project root:

```bash
uv run python -m glamtool.cli <command>
```

or if the virtual environment is activated:

```bash
python -m glamtool.cli <command>
```

---

## Commands

### sanity

Test connectivity to the Ghost Content API.

```bash
python -m glamtool.cli sanity
```

Confirms:

- `.env` is loaded
- API key works
- Ghost is reachable

---

### posts

List posts with flexible filtering.

```bash
python -m glamtool.cli posts
```

Options:

| Option                                   | Description                             |
| ---------------------------------------- | --------------------------------------- |
| `--limit N`                              | Number of posts (max 100 per page)      |
| `--published-only / --no-published-only` | Filter by published status              |
| `--missing-images-only`                  | Only posts without feature images       |
| `--tag TAG`                              | Filter by tag (repeatable)              |
| `--any-tag`                              | Match ANY tag (OR) instead of ALL (AND) |
| `--filter "..."`                         | Raw Ghost filter expression             |

Examples:

Show published Song Picks:

```bash
python -m glamtool.cli posts --tag song-pick
```

Require multiple tags (AND):

```bash
python -m glamtool.cli posts --tag song-pick --tag 2026
```

Match any of multiple tags (OR):

```bash
python -m glamtool.cli posts --tag song-pick --tag review --any-tag
```

Use raw filter:

```bash
python -m glamtool.cli posts --filter 'title:~"Olympics"'
```

Combine:

```bash
python -m glamtool.cli posts --tag song-pick --filter 'title:~"London"'
```

---

### export-posts

Export posts to CSV.

```bash
python -m glamtool.cli export-posts
```

Options:

| Option             | Description                 |
| ------------------ | --------------------------- |
| `--out PATH`       | Output CSV path             |
| `--published-only` | Export only published posts |
| `--tag TAG`        | Filter by tag               |
| `--any-tag`        | Match ANY tag               |
| `--filter "..."`   | Raw Ghost filter            |

Example:

```bash
python -m glamtool.cli export-posts --tag song-pick --out exports/song_picks.csv
```

---

### export-markdown

Export posts to Markdown.

```bash
python -m glamtool.cli export-markdown --tag song-pick --week 2026-06-25 --format post
```

Options:

| Option             | Description                                      |
| ------------------ | ------------------------------------------------ |
| `--out PATH`       | Output Markdown path; omit to print to stdout    |
| `--format FORMAT`  | `post` for full posts or `header` for title list |
| `--published-only` | Export only published posts                      |
| `--tag TAG`        | Filter by tag                                    |
| `--any-tag`        | Match ANY tag                                    |
| `--filter "..."`   | Raw Ghost filter                                 |
| `--start-date DATE`| Include posts on or after `YYYY-MM-DD`           |
| `--end-date DATE`  | Include posts on or before `YYYY-MM-DD`          |
| `--week DATE`      | Seven days starting with `YYYY-MM-DD`            |

Full post export:

```bash
python -m glamtool.cli export-markdown --tag song-pick --week 2026-06-18 --format post --out exports/song_picks.md
```

Linked header list:

```bash
python -m glamtool.cli export-markdown --tag song-pick --week 2026-06-18 --format header
```

The `post` format writes each title as a level-two heading and converts Ghost HTML content to Markdown. YouTube embeds are emitted as plain links.

---

## Filtering Model

Ghost filters are combined using `+` (logical AND).

Examples of valid Ghost filters:

- `status:published`
- `feature_image:null`
- `tag:song-pick`
- `tag:[song-pick,review]`
- `title:~"London"`
- `published_at:>='2026-06-22'`
- `published_at:<'2026-06-29'`

When using CLI options, filters are automatically combined.

---

## Architecture Overview

```
CLI (Typer)
   ↓
GhostContentClient (httpx)
   ↓
Ghost Content API
   ↓
Dataclass models
   ↓
Terminal output (Rich) or CSV export
```

### Key Components

- `config.py` — loads environment configuration
- `ghost.py` — API client + pagination logic
- `cli.py` — command definitions
- `GhostPost` dataclass — structured API result

---

## Design Philosophy

- Minimal abstraction
- Clear data flow
- Typed configuration
- Safe defaults
- Extensible for AI tooling

This tool is intentionally small and composable, making it ideal for:

- Editorial automation
- Content audits
- AI-assisted workflows
- Personal data tooling

---

## Roadmap Ideas

Potential next additions:

- `tags` command to list available tags
- `dump-post --slug` to export a single post as JSON/Markdown
- `generate-social` using OpenAI
- Caching layer
- Async API calls
- Admin API support (write operations)

---

## License

Personal tooling — adapt as needed.

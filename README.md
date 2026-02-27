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
- Sanity check API connectivity
- Clean CLI built with Typer
- Pretty terminal output via Rich
- Configuration via environment variables

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

From the project directory:

```bash
uv sync
```

Optional (to run `glamtool` without `uv run` in the current shell):

```bash
source .venv/bin/activate
```

Set real environment variables (recommended), e.g. in your shell profile:

```bash
export GHOST_URL="https://your-site.com"
export GHOST_CONTENT_KEY="YOUR_CONTENT_API_KEY"
```

Optional: use a `.env` file and pass it explicitly:

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
uv run glamtool <command>
```

or if the virtual environment is activated and the package is installed:

```bash
glamtool <command>
```

If you use a dotenv file, pass it explicitly:

```bash
glamtool --env-file /path/to/.env <command>
```

---

## Commands

### sanity

Test connectivity to the Ghost Content API.

```bash
glamtool sanity
```

Confirms:

- environment variables are set and valid
- API key works
- Ghost is reachable

---

### posts

List posts with flexible filtering.

```bash
glamtool posts
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
glamtool posts --tag song-pick
```

Require multiple tags (AND):

```bash
glamtool posts --tag song-pick --tag 2026
```

Match any of multiple tags (OR):

```bash
glamtool posts --tag song-pick --tag review --any-tag
```

Use raw filter:

```bash
glamtool posts --filter 'title:~"Olympics"'
```

Combine:

```bash
glamtool posts --tag song-pick --filter 'title:~"London"'
```

---

### export-posts

Export posts to CSV.

```bash
glamtool export-posts
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
glamtool export-posts --tag song-pick --out exports/song_picks.csv
```

---

## Filtering Model

Ghost filters are combined using `+` (logical AND).

Examples of valid Ghost filters:

- `status:published`
- `feature_image:null`
- `tag:song-pick`
- `tag:[song-pick,review]`
- `title:~"London"`

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

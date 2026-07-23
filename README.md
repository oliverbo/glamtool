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
- Publish Markdown files as Ghost drafts
- Sanity check API connectivity
- Clean CLI built with Typer
- Pretty terminal output via Rich
- Configuration via `.env`

---

## Requirements

- macOS (tested)
- Python 3.12+
- `uv` (recommended) or `venv`

Install `uv`:

```bash
brew install uv
```

---

## Setup

Clone or create the project directory, then:

```bash
uv sync
```

To make the `glamtool` command available outside the project directory, install it as an
editable uv tool:

```bash
uv tool install --editable .
```

Refresh an existing tool installation after pulling dependency changes:

```bash
uv tool install --force --editable .
```

Create a `.env` file:

```env
GHOST_URL="https://your-site.com"
GHOST_CONTENT_KEY="YOUR_CONTENT_API_KEY"
GHOST_ADMIN_KEY="YOUR_ADMIN_API_ID:YOUR_ADMIN_API_SECRET"
```

You can generate a Content API key in Ghost Admin under:

Settings → Integrations → Custom Integration

The Admin API key is only required for the `publish` command. Keep it private: it can create
and modify content in Ghost.

---

## Running Commands

From the project root:

```bash
uv run glamtool <command>
```

or, after installing the uv tool:

```bash
glamtool <command>
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

### publish

Create a Ghost draft from a Markdown file:

```bash
python -m glamtool.cli publish drafts/new-post.md
```

The command always creates a draft. It never publishes a post directly. The first heading is
used as the title and removed from the body. The first image is uploaded, used as the featured
image, and removed from the body. Other local images are uploaded and their body URLs are
rewritten to the Ghost URLs.

Tags and authors can be supplied as YAML front matter. Ghost identifies authors by email:

```markdown
---
tags:
  - Reviews
  - Music
authors:
  - editor@example.com
audience: subscribers
---

# The post title

![Featured image](images/cover.jpg)

Hello, [%audience].

/sections/intro.md
Audience: new subscribers

/images/chart.png "Chart caption"
```

iA Writer may store content blocks without a leading slash when the referenced file is in the
same folder. Bare references such as `images/cover.jpg` and `Mallory Hawk.jpg` are supported too.

The publisher supports iA Writer-style content blocks for Markdown/text files, Ghost-supported
images (`gif`, `jpeg`, `jpg`, `png`, `svg`, and `webp`), CSV tables, and UTF-8 code files.
Included files may contain further content blocks. Paths are resolved relative to the file that
contains them and must remain inside the main document's folder. Recursive includes are rejected.

Document metadata and content-block metadata can be inserted with `[%name]`. Content-block
metadata may be written as consecutive `Key: value` lines or enclosed in `---` delimiters.

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

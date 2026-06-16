# Contributing

## Setup

Proxhy is a [uv](https://docs.astral.sh/uv/) project. To set it up:

```bash
uv sync --group dev
```

## Before opening a PR

Make sure to run pre-commit:

```bash
uv run pre-commit run --all-files
```

Exclude `--all-files` to run it on only changes that you've added with `git add`.

To auto-fix lint and format issues:

```bash
uv run ruff check --fix . && uv run ruff format .
```

Type errors from pyrefly must be fixed manually.

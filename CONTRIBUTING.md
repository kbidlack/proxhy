# Contributing

## Setup

Proxhy is a [uv](https://docs.astral.sh/uv/) project.

```bash
uv sync --group dev
uv run pre-commit install
```

## Before opening a PR

Checks run automatically on commit via pre-commit. To run them manually:

```bash
uv run pre-commit run --all-files
```

Exclude `--all-files` to run it on only changes that you've added with `git add`.

To auto-fix lint and format issues:

```bash
uv run ruff check --fix . && uv run ruff format .
```

Type errors from pyrefly must be fixed manually.

# Contributing

## Setup

```bash
uv sync --group dev
```

## Before opening a PR

Run checks:

```bash
uv run task ci-lint
uv run task typecheck
```

If lint/format fails, try auto-fixing it:

```bash
uv run task lint
```

Then re-run `uv run task ci-lint` to confirm. Type errors from pyrefly must be fixed manually.

## Tasks

| Command                 | Description                      |
| ----------------------- | -------------------------------- |
| `uv run task ci-lint`   | Check lint and format (no fixes) |
| `uv run task typecheck` | Run type checker                 |
| `uv run task lint`      | Auto-fix lint and format issues  |

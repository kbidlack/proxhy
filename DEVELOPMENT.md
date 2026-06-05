# Development

Mostly notes for myself so I don't forget how to release...

## Releasing

The workflow for releases is as follows:

1. Bump the version in `pyproject.toml` to `<VERSION>`, where `<VERSION>` is of the format `YYYY.MM.DD` with optional `.postX`
2. Double check that the project runs correctly with the new version (`uv run proxhy`)
3. `uv sync --upgrade` to upgrade `uv.lock`
4. `git commit -m "version <VERSION>"`, `git tag v<VERSION>`, `git push origin main`, and `git push origin main --tags`
5. Add release notes to the release created by the workflow run

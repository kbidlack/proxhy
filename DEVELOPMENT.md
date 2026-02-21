# Development

Development happens on the `dev` branch. `main` is reserved for releases.

## Releasing

The workflow for releases is as follows:

1. (On dev branch) Double check that the project runs correctly with the new version (`uv run proxhy`).
2. Bump the version in `pyproject.toml` to `<VERSION>`, where `<VERSION>` is of the format `YYYY.MM.DD`. If there was already a release today, add `.postX` to the version.
3. `uv sync --upgrade` to upgrade `uv.lock`.
4. Commit (and push) the merge bump change to the dev branch (can be committed with other changes).
5. `git checkout main` and `git merge dev -m "release <VERSION>" --no-ff`.
6. `git tag v<VERSION>`.
7. `git push origin main` and `git push origin main --tags`.
8. Create a new release on GitHub with the new tag and title it with the release number (no v).
9. `git checkout dev`, `git merge main`, `git push origin dev`.

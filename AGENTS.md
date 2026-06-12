# AGENTS.md

## Project Structure

This is a uv workspace monorepo with packages in `packages/`:
- **shared** (`inky-image-display-shared`): SQLModel models + Pydantic schemas shared across services
- **sync** (`inky-image-display-sync`): Immich image sync service
- **controller** (`inky-image-display-controller`): Inky e-ink display controller
- **api** (`inky-image-display-api`): FastAPI service for device/image management; also serves the built web frontend and the /media image proxy
- **web** (`inky-image-display-web`): React operator UI (npm, not part of the uv workspace)

## Core Commands

Add a dependency to a specific package
```bash
uv add --package inky-image-display pydantic~=2.9.0
```
Apply formatting and Check code quality and Validate types. Always run after the end of a task.
```bash
uv run ruff check --fix . && uv run ruff format . && uv run ty check --fix
```
Install all workspace dependencies
```bash
uv sync --group dev --all-packages
```
Always use uv for any python module/code
```bash
uv run pytest
uv run python3 -c "print(1);"
```
Run the Playwright e2e suite after frontend changes (local only, not in CI). Needs a running API serving the fresh build — see packages/web/README.md.
```bash
cd packages/web && npm run build && npm run test:e2e
```

## Development Guidelines

- **Code Documentation**: Document the *why* a code does what it does not what it does and always check if documentation needs to be updates after making medium to large changes.
- **Enduser and Developer Documentation** is written in Markdown and stored in ./docs folder.
- Validate all external inputs with pydantic or pydantic-settings
- All changes must be tested. If you're not testing your changes, you're not done.
- If **outdated** tests block your implementation suggest changing them.
- Follow existing code style. Check neighboring files for patterns.
- **Clear commit messages**: Explain the *why* a change was done not what the change was, use conventional commits, keep commit message length below 300 characters

# inky-image-display

[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=fff)](#)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v0.json)](https://github.com/charliermarsh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

A centralised system for driving one or more [Pimoroni Inky](https://github.com/pimoroni/inky) e-ink displays from a single service, with automatic image sync from [Immich](https://immich.app/) and optional on-demand AI image generation via Gemini.

## What it does

- **Manage many displays from one place.** A central API tracks devices, images, and schedules; lightweight controllers on each Raspberry Pi receive commands over MQTT and pull images from S3-compatible storage.
- **Sync from Immich.** A cron-driven job pulls photos that match album / people / tag / date filters, resizes them to each display's native resolution, and rotates them on-device.
- **Coordinate displays into a grid.** Two or more Inky panels can be arranged on a shared physical canvas (cm-based) and jointly show slices of a single image — the API pre-renders each device's crop, no grid-aware code on the controllers.
- **Generate images on demand.** A NiceGUI web UI can call Gemini to create images on a subject and push them straight to a matching online display.

## Architecture

```
┌──────────────────────┐    MQTT broker     ┌─────────────────────┐
│   Controller(s)      │◄──────────────────►│   API               │
│   (Raspberry Pi)     │  HTTP /register    │   (FastAPI)         │
│   inky-controller    │  S3 (images)       │   :8000             │
└──────────────────────┘◄───────────────────└─────────────────────┘
                                                      ▲
                                            ┌─────────┴─────────┐
                                            │                   │
                                  ┌─────────┴────────┐ ┌────────┴────────┐
                                  │   UI             │ │   Sync          │
                                  │   (NiceGUI)      │ │   (CLI/Cron)    │
                                  │   :8001          │ │   immich/gemini │
                                  └──────────────────┘ └─────────────────┘
```

- **API** — FastAPI service. Device registry, image library, sync-job CRUD, MQTT command dispatch, grid pre-rendering, on-demand Gemini generation.
- **Controller** — Daemon on the Raspberry Pi attached to an Inky display. Registers over HTTP, then connects to MQTT, fetches images from S3, and refreshes the screen.
- **UI** — NiceGUI web app for browsing images, managing displays and grids, configuring sync jobs, and triggering AI generation. No auth — trusted LAN only.
- **Sync** — CLI tool with `immich` and `gemini` subcommands, run from cron.

See [docs/main.md](docs/main.md) for the full component breakdown and MQTT topic reference.

## Quick start

```bash
# Install all dependencies
uv sync --group dev --all-packages

# Run the API
uv run inky-image-display-api

# Run the UI
uv run --package inky-image-display-ui inky-image-display-ui

# Run the controller (on a Raspberry Pi, with a config file)
uv run inky-controller --config /etc/inky/config.yaml

# Run an Immich sync (or append --dry-run to preview)
uv run inky-image-display-sync immich
```

The API and UI both need an S3-compatible store (MinIO / Garage / AWS) and an MQTT broker. See [docs/deployment-requirements.md](docs/deployment-requirements.md) for the full list and [docs/configuration.md](docs/configuration.md) for environment variables.

## Documentation

- [Architecture and component overview](docs/main.md) — components, data flow, MQTT topics
- [Configuration reference](docs/configuration.md) — environment variables per service
- [Deployment requirements](docs/deployment-requirements.md) — external dependencies and minimal env
- [UI guide](docs/ui.md) — pages, routes, local development
- [Grids](docs/grids.md) — multi-display canvas layout and slice rendering

## License

See [LICENSE](LICENSE).

# inky-image-display

[![Copier](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-orange.json)](https://github.com/copier-org/copier)
[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=fff)](#)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v0.json)](https://github.com/charliermarsh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

A system for displaying images on Pimoroni Inky e-ink displays, with automatic sync from [Immich](https://immich.app/).

## Architecture

```
┌──────────────────────┐     WebSocket      ┌─────────────────────┐
│   Controller         │◄───────────────────│   API               │
│   (Raspberry Pi)     │                    │   (FastAPI)         │
│   inky-controller    │     S3 (images)    │   :8000             │
└──────────────────────┘◄───────────────────└─────────────────────┘
                                                      │
                                              ┌───────┴───────┐
                                              │  PostgreSQL   │
                                              │  S3 Storage   │
                                              └───────┬───────┘
                                                      │
                                            ┌─────────▼───────┐
                                            │   Sync          │
                                            │   (CLI/CronJob) │
                                            │   immich-sync   │
                                            └─────────────────┘
```

**API** — FastAPI service. Manages devices, images, and sync jobs. Devices connect via WebSocket for registration and command delivery. Serves image metadata and presigned S3 URLs to the controller.

**Controller** — Daemon that runs on a Raspberry Pi. Connects to the API via WebSocket, receives display commands, fetches images from S3, and drives the Inky display.

**Sync** — CLI tool run as a cron job. Reads sync job configuration from the database, fetches images from Immich, and stores them in S3.

## Quick Start

```bash
# Install all dependencies
uv sync --group dev

# Run the API
uv run inky-image-display-api

# Run the controller (on a Raspberry Pi, with a config file)
uv run inky-controller --config /etc/inky/config.yaml

# Run the Immich sync
uv run immich-sync

# Dry-run: preview what would be synced
uv run immich-sync --dry-run
```

## Documentation

- [Architecture and component overview](docs/main.md)
- [Configuration reference](docs/configuration.md)
- [Deployment requirements](docs/deployment-requirements.md)

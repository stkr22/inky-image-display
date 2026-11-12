"""Single place where Gemini clients are built.

Every Gemini call in the project goes through :func:`open_async_client` so
the transport settings below cannot drift between the image, text and vision
helpers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from google import genai
from google.genai import types

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from google.genai.client import AsyncClient

# google-genai 3.0 moved the Developer API default from v1beta to v1. Every
# feature we rely on — image output (response_modalities=IMAGE + image_config),
# response_schema and the google_search tool — was verified against v1beta, so
# pin it rather than let an SDK bump silently change request semantics. An
# explicit ``http_options.api_version`` is patched over the SDK's defaults
# *after* it reads ``GOOGLE_GENAI_API_VERSION``, so that env var no longer has
# any effect; changing the version is a code change on purpose.
GEMINI_API_VERSION = "v1beta"

# The SDK's default timeout is None, i.e. a stalled connection blocks a sync
# job or an API generation task forever. Image generation is the slowest call
# (tens of seconds under load), so 120 s leaves headroom while still bounding
# a hung request.
DEFAULT_TIMEOUT_S = 120.0


def build_client(api_key: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> genai.Client:
    """Return a Gemini client pinned to :data:`GEMINI_API_VERSION` with a request timeout."""
    return genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version=GEMINI_API_VERSION,
            # HttpOptions.timeout is in milliseconds.
            timeout=int(timeout_s * 1000),
        ),
    )


@asynccontextmanager
async def open_async_client(api_key: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> AsyncGenerator[AsyncClient]:
    """Yield the async side of a fresh client and close both transports afterwards.

    The async client makes requests cancellable from the event loop (a worker
    thread running the sync client could not be interrupted on shutdown).
    ``Client.aio.aclose()`` only closes the async transport, so the sync one the
    SDK builds eagerly is closed explicitly instead of waiting for ``__del__``.
    """
    client = build_client(api_key, timeout_s=timeout_s)
    try:
        async with client.aio as aio:
            yield aio
    finally:
        client.close()

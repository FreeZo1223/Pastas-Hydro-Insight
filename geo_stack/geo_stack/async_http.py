"""Asynchrone HTTP-laag voor geo_stack skills.

Biedt een httpx.AsyncClient met retry-logica voor parallelle fetches
in de LESA-agent orchestrator. Skills gebruiken dit voor hun
``async_fetch_*``-varianten.

Gebruik:
    async with async_client() as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

log = logging.getLogger(__name__)

_USER_AGENT = "geo_stack/0.2 (NL geospatial automation)"

# Statuscodes waarvoor we retrien (zelfde als sync requests.Session)
_RETRY_STATUS = {429, 500, 502, 503, 504}


@asynccontextmanager
async def async_client(
    *,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Context-manager die een geconfigureerde httpx.AsyncClient levert.

    Retry-logica is hier bewust eenvoudig gehouden: httpx heeft geen
    ingebouwde urllib3-stijl retry. Voor PDOK-calls gebruiken we exponential
    backoff via een handmatige retry-loop in de skill-functies zelf, of via
    de sync-in-executor aanpak in async_fetch_*.
    """
    transport = httpx.AsyncHTTPTransport(retries=max_retries)
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        timeout=httpx.Timeout(timeout, connect=10.0),
        transport=transport,
        follow_redirects=True,
    ) as client:
        yield client


async def async_get_json(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 30.0,
) -> dict:
    """Convenience: GET + JSON-parse in één aanroep."""
    async with async_client(timeout=timeout) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


async def async_get_bytes(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 300.0,
) -> bytes:
    """Convenience: GET + bytes-response (voor WCS rasters, WFS GeoJSON)."""
    async with async_client(timeout=timeout) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.content

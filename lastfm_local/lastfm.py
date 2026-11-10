"""Last.fm artist chart client.

The client depends only on an object that exposes ``get(url, params=...)`` as
an async context manager, which is the shape of aiohttp's ``ClientSession``.
Music Assistant imports stay in ``provider.py``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .matching import ChartTrack

API_URL = "https://ws.audioscrobbler.com/2.0/"

# https://www.last.fm/api/errorcodes
AUTH_ERROR_CODES = frozenset({4, 9, 10, 13, 26})
RETRYABLE_ERROR_CODES = frozenset({11, 16, 29})


class LastFmError(Exception):
    """Last.fm rejected a call or the response could not be read."""

    def __init__(self, message: str, *, code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable

    @property
    def auth_failed(self) -> bool:
        """Whether the API key was rejected."""
        return self.code in AUTH_ERROR_CODES


def parse_duration(value: object) -> int | None:
    """Return a track length in seconds.

    Last.fm usually reports seconds. Values that can only be milliseconds
    (above 10000) are converted. Zero means the length is unknown.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        length = value
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        length = int(value.strip())
    else:
        return None
    if length <= 0:
        return None
    if length > 10000:
        length //= 1000
    return length or None


def parse_top_tracks(payload: dict[str, Any]) -> list[ChartTrack]:
    """Parse an ``artist.getTopTracks`` body into ranked chart rows.

    :raises LastFmError: When Last.fm returned an error object.
    """
    raise_for_payload(payload)
    container = payload.get("toptracks") or {}
    raw_tracks = container.get("track") if isinstance(container, dict) else None
    if isinstance(raw_tracks, dict):
        raw_tracks = [raw_tracks]
    if not isinstance(raw_tracks, list):
        return []

    chart: list[ChartTrack] = []
    for index, raw in enumerate(raw_tracks):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("name") or "").strip()
        if not title:
            continue
        artist_data = raw.get("artist")
        if isinstance(artist_data, dict):
            artist = str(artist_data.get("name") or "").strip()
        elif isinstance(artist_data, str):
            artist = artist_data.strip()
        else:
            artist = ""
        mbid = str(raw.get("mbid") or "").strip() or None
        chart.append(
            ChartTrack(
                title=title,
                artist=artist,
                mbid=mbid,
                duration=parse_duration(raw.get("duration")),
                rank=index,
            )
        )
    return chart


def raise_for_payload(payload: dict[str, Any]) -> None:
    """Raise when the body is a Last.fm error object."""
    if "error" not in payload:
        return
    try:
        code = int(payload.get("error") or 0)
    except (TypeError, ValueError):
        code = 0
    message = str(payload.get("message") or "Unknown Last.fm error")
    raise LastFmError(
        f"Last.fm API error {code}: {message}",
        code=code,
        retryable=code in RETRYABLE_ERROR_CODES,
    )


class LastFmClient:
    """Minimal read-only client for artist top tracks."""

    def __init__(self, session: Any, api_key: str, *, min_interval: float = 0.2) -> None:
        """
        :param session: aiohttp-like session (``async with session.get(...)``).
        :param api_key: Last.fm API key. Not logged.
        :param min_interval: Minimum seconds between calls. Tests pass 0.
        """
        self._session = session
        self._api_key = api_key
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def ping(self) -> None:
        """Check that the API key is accepted.

        A network failure propagates as :class:`LastFmError` with no code, or
        with a retryable code. Authentication failures set :attr:`LastFmError.auth_failed`.
        """
        await self._call("chart.getTopTracks", limit=1)

    async def artist_top_tracks(
        self,
        artist: str,
        mbid: str | None,
        limit: int,
    ) -> list[ChartTrack]:
        """Return an artist's global top tracks, most played first.

        A MusicBrainz id is tried first. Last.fm's MBID index is sparse, so an
        empty result or a non-auth error falls back to the artist name.
        """
        limit = max(1, min(int(limit), 50))
        if mbid:
            try:
                tracks = await self._top_tracks({"mbid": mbid, "limit": limit})
            except LastFmError as err:
                if err.auth_failed:
                    raise
                tracks = []
            if tracks:
                return tracks
        if not artist:
            return []
        return await self._top_tracks({"artist": artist, "autocorrect": 1, "limit": limit})

    async def _top_tracks(self, params: dict[str, Any]) -> list[ChartTrack]:
        payload = await self._call("artist.getTopTracks", **params)
        return parse_top_tracks(payload)

    async def _call(self, method: str, **params: Any) -> dict[str, Any]:
        query = {
            "method": method,
            "api_key": self._api_key,
            "format": "json",
            **params,
        }
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            try:
                async with self._session.get(API_URL, params=query) as response:
                    status = getattr(response, "status", 200)
                    if status >= 400:
                        raise LastFmError(
                            f"Last.fm HTTP {status} for {method}",
                            retryable=status >= 500,
                        )
                    payload = await response.json(content_type=None)
            except LastFmError:
                raise
            except TimeoutError as err:
                raise LastFmError(f"Last.fm timed out during {method}", retryable=True) from err
            except Exception as err:
                raise LastFmError(f"Last.fm request failed during {method}: {err}") from err

        if not isinstance(payload, dict):
            raise LastFmError(f"Last.fm returned an unexpected payload for {method}")
        raise_for_payload(payload)
        return payload

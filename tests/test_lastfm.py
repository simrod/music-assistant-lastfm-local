"""Last.fm payload and client tests. No network and no Music Assistant."""

from __future__ import annotations

import asyncio

import pytest
from lastfm_local.lastfm import (
    API_URL,
    LastFmClient,
    LastFmError,
    parse_duration,
    parse_top_tracks,
)


class _Response:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status = status

    async def json(self, content_type: str | None = None) -> dict:
        del content_type
        return self._payload

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class _Session:
    def __init__(self, payloads: list[dict]) -> None:
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    def get(self, url: str, params: dict | None = None) -> _Response:
        assert url == API_URL
        assert params is not None
        self.calls.append(params)
        assert params["api_key"] == "test-key"
        return _Response(self._payloads.pop(0))


def _payload(*tracks: dict) -> dict:
    return {"toptracks": {"track": list(tracks)}}


def test_parse_top_tracks_list_single_object_and_duration() -> None:
    chart = parse_top_tracks(
        _payload(
            {
                "name": "Creep",
                "mbid": "rec-1",
                "duration": "238",
                "artist": {"name": "Radiohead", "mbid": "art-1"},
            },
            {"name": "  ", "duration": "0"},
        )
    )
    assert len(chart) == 1
    assert chart[0].title == "Creep"
    assert chart[0].artist == "Radiohead"
    assert chart[0].mbid == "rec-1"
    assert chart[0].duration == 238
    assert chart[0].rank == 0

    single = parse_top_tracks(
        {"toptracks": {"track": {"name": "Idioteque", "artist": "Radiohead", "duration": 180000}}}
    )
    assert single[0].title == "Idioteque"
    assert single[0].artist == "Radiohead"
    assert single[0].duration == 180
    assert parse_duration(0) is None
    assert parse_duration(True) is None
    assert parse_duration("nope") is None


def test_parse_top_tracks_raises_api_errors() -> None:
    with pytest.raises(LastFmError) as raised:
        parse_top_tracks({"error": 10, "message": "Invalid API key"})
    assert raised.value.auth_failed
    assert raised.value.code == 10


def test_client_prefers_mbid_then_falls_back_to_the_artist_name() -> None:
    empty = {"toptracks": {"track": []}}
    session = _Session([empty, _payload({"name": "Creep", "artist": "Radiohead"})])
    client = LastFmClient(session, "test-key", min_interval=0)

    chart = asyncio.run(client.artist_top_tracks("Radiohead", "art-1", 10))

    assert [track.title for track in chart] == ["Creep"]
    assert session.calls[0]["method"] == "artist.getTopTracks"
    assert session.calls[0]["mbid"] == "art-1"
    assert "artist" not in session.calls[0]
    assert session.calls[1]["artist"] == "Radiohead"
    assert session.calls[1]["autocorrect"] == 1


def test_client_does_not_fall_back_when_the_key_is_rejected() -> None:
    session = _Session([{"error": 10, "message": "Invalid API key"}])
    client = LastFmClient(session, "test-key", min_interval=0)
    with pytest.raises(LastFmError) as raised:
        asyncio.run(client.artist_top_tracks("Radiohead", "art-1", 10))
    assert raised.value.auth_failed
    assert len(session.calls) == 1


def test_ping_uses_a_chart_call() -> None:
    session = _Session([{"tracks": {"track": []}}])
    client = LastFmClient(session, "test-key", min_interval=0)
    asyncio.run(client.ping())
    assert session.calls[0]["method"] == "chart.getTopTracks"
    assert session.calls[0]["limit"] == 1

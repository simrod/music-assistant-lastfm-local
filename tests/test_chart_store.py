"""Saved-chart envelope tests. These do not import Music Assistant."""

from lastfm_local.matching import (
    ChartTrack,
    chart_refresh_days,
    empty_chart_replaces,
    pack_stored_chart,
    stored_chart_is_fresh,
    unpack_stored_chart,
)


def _track() -> ChartTrack:
    return ChartTrack(title="Karma Police", artist="Radiohead", mbid="abc", duration=260, rank=0)


def test_pack_unpack_round_trip_including_empty() -> None:
    tracks = [_track()]
    assert unpack_stored_chart(pack_stored_chart(tracks, 1_700_000_000)) == (tracks, 1_700_000_000)
    assert unpack_stored_chart(pack_stored_chart([], 1_700_000_000)) == ([], 1_700_000_000)


def test_legacy_list_has_no_fetched_at() -> None:
    tracks = [_track()]
    legacy = [track.as_dict() for track in tracks]
    assert unpack_stored_chart(legacy) == (tracks, None)


def test_unpack_rejects_bad_payloads() -> None:
    assert unpack_stored_chart(None) is None
    assert unpack_stored_chart("chart") is None
    assert unpack_stored_chart({"fetched_at": 1}) is None
    assert unpack_stored_chart([{"artist": "Radiohead"}]) is None
    assert unpack_stored_chart({"fetched_at": 1, "tracks": [{"artist": "Radiohead"}]}) is None


def test_freshness_window() -> None:
    interval = 42 * 24 * 60 * 60
    fetched_at = 1_000_000
    assert stored_chart_is_fresh(fetched_at, fetched_at + interval - 1, interval)
    assert not stored_chart_is_fresh(fetched_at, fetched_at + interval, interval)
    assert not stored_chart_is_fresh(None, fetched_at, interval)


def test_chart_refresh_days_clamps() -> None:
    assert chart_refresh_days(None) == 42
    assert chart_refresh_days("42") == 42
    assert chart_refresh_days("nope") == 42
    assert chart_refresh_days(0) == 1
    assert chart_refresh_days(9999) == 365


def test_empty_chart_does_not_replace_tracks() -> None:
    assert empty_chart_replaces([_track()]) is False
    assert empty_chart_replaces(None) is True
    assert empty_chart_replaces([]) is True

"""Matcher tests. These do not import Music Assistant."""

from lastfm_local.matching import (
    ChartTrack,
    LibraryTrackRef,
    match_chart_to_library,
    title_key,
)


def _chart(
    title: str,
    *,
    rank: int = 0,
    mbid: str | None = None,
    duration: int | None = None,
) -> ChartTrack:
    return ChartTrack(title=title, artist="Radiohead", mbid=mbid, duration=duration, rank=rank)


def _lib(
    key: str,
    title: str,
    *,
    version: str = "",
    mbid: str | None = None,
    duration: int | None = None,
    available: bool = True,
) -> LibraryTrackRef:
    return LibraryTrackRef(
        key=key,
        title=title,
        version=version,
        recording_mbid=mbid,
        duration=duration,
        available=available,
    )


def test_title_key_strips_version_decoration_and_keeps_real_subtitles() -> None:
    assert title_key("Paranoid Android - 2011 Remaster") == "paranoid android"
    assert title_key("Paranoid Android (Remastered 2011)") == "paranoid android"
    assert title_key("Creep (feat. Someone)") == "creep"
    assert title_key("Café del Mar") == "cafe del mar"
    assert title_key("Song & Dance") == "song and dance"
    assert title_key("Song (Part 1)") == "song part 1"
    assert title_key("Creep (Live at the BBC)") == "creep"


def test_chart_order_is_kept_and_missing_titles_are_skipped() -> None:
    chart = [
        _chart("Creep", rank=0),
        _chart("Not In Library", rank=1),
        _chart("Karma Police", rank=2),
    ]
    library = [
        _lib("karma", "Karma Police"),
        _lib("creep", "Creep"),
    ]
    assert match_chart_to_library(chart, library, limit=25) == ["creep", "karma"]


def test_studio_copy_beats_live_unless_the_chart_row_is_live() -> None:
    library = [
        _lib("live", "Creep", version="Live"),
        _lib("studio", "Creep"),
    ]
    assert match_chart_to_library([_chart("Creep")], library, limit=5) == ["studio"]
    assert match_chart_to_library([_chart("Creep (Live)")], library, limit=5) == ["live"]


def test_live_copy_is_used_when_it_is_the_only_one() -> None:
    library = [_lib("live", "Creep", version="Live at the BBC")]
    assert match_chart_to_library([_chart("Creep")], library, limit=5) == ["live"]


def test_same_library_track_is_not_returned_twice() -> None:
    chart = [
        _chart("Creep", rank=0),
        _chart("Creep - 2011 Remaster", rank=1),
        _chart("Karma Police", rank=2),
    ]
    library = [_lib("creep", "Creep"), _lib("karma", "Karma Police")]
    assert match_chart_to_library(chart, library, limit=25) == ["creep", "karma"]


def test_recording_mbid_wins_and_a_different_mbid_does_not_reject() -> None:
    library = [
        _lib("title", "Creep"),
        _lib("mbid", "Something Else", mbid="rec-1"),
    ]
    chart = [_chart("Creep", mbid="rec-1")]
    assert match_chart_to_library(chart, library, limit=5) == ["mbid"]

    remaster = [_lib("remaster", "Creep", mbid="rec-other")]
    matched = match_chart_to_library([_chart("Creep", mbid="rec-1")], remaster, limit=5)
    assert matched == ["remaster"]


def test_closer_duration_wins_a_title_tie() -> None:
    library = [
        _lib("far", "Creep", duration=400),
        _lib("near", "Creep", duration=238),
    ]
    assert match_chart_to_library([_chart("Creep", duration=240)], library, limit=5) == ["near"]


def test_available_copy_beats_a_missing_file() -> None:
    library = [
        _lib("gone", "Creep", available=False),
        _lib("here", "Creep"),
    ]
    assert match_chart_to_library([_chart("Creep")], library, limit=5) == ["here"]


def test_short_titles_do_not_match_longer_ones() -> None:
    library = [_lib("long", "One More Time"), _lib("letters", "R.E.M. song")]
    assert match_chart_to_library([_chart("One")], library, limit=5) == []
    assert match_chart_to_library([_chart("REM")], [_lib("band", "R.E.M.")], limit=5) == ["band"]


def test_limit_stops_the_row() -> None:
    chart = [_chart("A", rank=0), _chart("B", rank=1), _chart("C", rank=2)]
    library = [_lib("a", "A"), _lib("b", "B"), _lib("c", "C")]
    assert match_chart_to_library(chart, library, limit=2) == ["a", "b"]


def test_chart_round_trip() -> None:
    original = _chart("Creep", rank=3, mbid="abc", duration=238)
    assert ChartTrack.from_dict(original.as_dict()) == original

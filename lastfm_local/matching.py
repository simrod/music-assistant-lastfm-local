"""Rank a local artist's tracks by a Last.fm global chart.

The matcher never talks to Last.fm or Music Assistant. It compares chart rows
with tracks the caller already loaded from the library and returns library
keys in chart order. A chart row with no library copy is skipped: a Last.fm
title that is not in the library cannot be played from local files.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Version words that describe a different performance of the same song.
# A chart row that does not ask for one of these prefers the plain recording,
# and falls back to the alternate when that is the only copy on disk.
_NOISE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("live", re.compile(r"\blive\b", re.IGNORECASE)),
    ("demo", re.compile(r"\bdemo\b", re.IGNORECASE)),
    ("remix", re.compile(r"\bremix(?:ed)?\b", re.IGNORECASE)),
    ("karaoke", re.compile(r"\bkaraoke\b", re.IGNORECASE)),
    ("instrumental", re.compile(r"\binstrumental\b", re.IGNORECASE)),
    ("acoustic", re.compile(r"\bacoustic\b", re.IGNORECASE)),
    ("rehearsal", re.compile(r"\brehearsal\b", re.IGNORECASE)),
    ("bootleg", re.compile(r"\bbootleg\b", re.IGNORECASE)),
    ("unplugged", re.compile(r"\bunplugged\b", re.IGNORECASE)),
    ("commentary", re.compile(r"\bcommentary\b", re.IGNORECASE)),
    ("mono", re.compile(r"\bmono\b", re.IGNORECASE)),
)

_FEAT_RE = re.compile(
    r"(?i)(?:\s*[\(\[]\s*)?\b(?:feat\.?|ft\.?|featuring)\b[^)\]]*?(?:[\)\]]|$)"
)
_TRAILING_VERSION_RE = re.compile(
    r"(?i)\s+[-–—]\s+(?:\d{4}\s+)?"
    r"(?:re-?master(?:ed)?|live|demo|remix(?:ed)?|acoustic|instrumental|mono|stereo)\b.*$"
)
_VERSION_PAREN_RE = re.compile(
    r"""(?ix)
    \s*[\(\[]\s*
    (?:
        (?:re-?master(?:ed)?|live(?:\s+at\b[^)\]]*)?|demo|remix(?:ed)?|acoustic|
           instrumental|karaoke|mono|stereo|radio|deluxe|anniversary|unplugged|
           session|bootleg|rehearsal|commentary)
        (?:\s+\d{2,4})?
        |
        \d{4}(?:\s+(?:re-?master(?:ed)?|mix|version))?
        |
        (?:single|album|radio)\s+version
    )
    \s*[\)\]]
    """
)
_PUNCT_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ChartTrack:
    """One Last.fm top-track row, most popular first when ``rank`` is 0."""

    title: str
    artist: str
    mbid: str | None
    duration: int | None
    rank: int

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable cache payload."""
        return {
            "title": self.title,
            "artist": self.artist,
            "mbid": self.mbid,
            "duration": self.duration,
            "rank": self.rank,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ChartTrack:
        """Rebuild a chart row from :meth:`as_dict`."""
        raw_duration = data.get("duration")
        duration = raw_duration if isinstance(raw_duration, int) and raw_duration > 0 else None
        raw_rank = data.get("rank")
        rank = raw_rank if isinstance(raw_rank, int) else 0
        raw_mbid = data.get("mbid")
        return cls(
            title=str(data.get("title") or ""),
            artist=str(data.get("artist") or ""),
            mbid=str(raw_mbid) if isinstance(raw_mbid, str) and raw_mbid else None,
            duration=duration,
            rank=rank,
        )


# How long a saved chart is reused before Last.fm is asked again.
# 42 days is 6 weeks. The provider setting is clamped to this range.
DEFAULT_CHART_REFRESH_DAYS = 42
MIN_CHART_REFRESH_DAYS = 1
MAX_CHART_REFRESH_DAYS = 365


def pack_stored_chart(tracks: list[ChartTrack], fetched_at: int) -> dict[str, object]:
    """Return the cache envelope for a chart fetched at ``fetched_at`` (Unix seconds)."""
    return {"fetched_at": fetched_at, "tracks": [track.as_dict() for track in tracks]}


def unpack_stored_chart(data: object) -> tuple[list[ChartTrack], int | None] | None:
    """Return ``(tracks, fetched_at)`` from a cache value, or ``None`` when it is unusable.

    A current value is ``{"fetched_at": int, "tracks": [...]}``. A chart stored
    before that envelope is a bare list of track dicts and has no ``fetched_at``.
    """
    if isinstance(data, list):
        tracks = _tracks_from_dicts(data)
        return None if tracks is None else (tracks, None)
    if not isinstance(data, dict):
        return None
    tracks = _tracks_from_dicts(data.get("tracks"))
    if tracks is None:
        return None
    raw_fetched = data.get("fetched_at")
    fetched_at = (
        raw_fetched
        if isinstance(raw_fetched, int) and not isinstance(raw_fetched, bool)
        else None
    )
    return tracks, fetched_at


def stored_chart_is_fresh(fetched_at: int | None, now: int, interval_seconds: int) -> bool:
    """Return whether a chart fetched at ``fetched_at`` is still inside the interval.

    A missing timestamp is stale, so the next lookup asks Last.fm. The chart is
    still returned when that call fails.
    """
    if fetched_at is None:
        return False
    return now - fetched_at < interval_seconds


def empty_chart_replaces(stored_tracks: list[ChartTrack] | None) -> bool:
    """Return whether an empty Last.fm response may be stored.

    An empty response must not replace a saved chart that already has tracks.
    It may be stored when nothing is saved, or when the saved chart is already empty.
    """
    return not stored_tracks


def chart_refresh_days(value: object) -> int:
    """Return a refresh interval in days, clamped to 1–365.

    A missing or non-numeric value becomes 42 days (6 weeks).
    """
    if isinstance(value, bool) or value is None:
        days = DEFAULT_CHART_REFRESH_DAYS
    elif isinstance(value, int):
        days = value
    elif isinstance(value, str):
        try:
            days = int(value.strip())
        except ValueError:
            days = DEFAULT_CHART_REFRESH_DAYS
    else:
        days = DEFAULT_CHART_REFRESH_DAYS
    return max(MIN_CHART_REFRESH_DAYS, min(days, MAX_CHART_REFRESH_DAYS))


def _tracks_from_dicts(items: object) -> list[ChartTrack] | None:
    """Return chart rows parsed from dicts. ``None`` when any row has no title."""
    if not isinstance(items, list):
        return None
    chart: list[ChartTrack] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("title"):
            return None
        chart.append(ChartTrack.from_dict(item))
    return chart


@dataclass(frozen=True, slots=True)
class LibraryTrackRef:
    """The fields the matcher needs from one in-library track."""

    key: str
    title: str
    version: str = ""
    recording_mbid: str | None = None
    duration: int | None = None
    available: bool = True


def title_key(title: str) -> str:
    """Return the song identity used for equality, without version decoration.

    Punctuation, accents, and featuring credits are removed. ``R.E.M.`` and
    ``REM`` share a compact form. Parenthetical text that is part of the title
    (``Song (Part 1)``) is kept.
    """
    text = unicodedata.normalize("NFKD", title)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("&", " and ")
    text = _FEAT_RE.sub(" ", text)
    text = _TRAILING_VERSION_RE.sub(" ", text)
    previous = None
    while previous != text:
        previous = text
        text = _VERSION_PAREN_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    return " ".join(text.split())


def noise_flags(text: str) -> frozenset[str]:
    """Return version tags present in a title or version string."""
    return frozenset(name for name, pattern in _NOISE_PATTERNS if pattern.search(text))


def _titles_match(chart_title: str, library_title: str) -> bool:
    chart_key = title_key(chart_title)
    library_key = title_key(library_title)
    if chart_key and chart_key == library_key:
        return True
    chart_compact = chart_key.replace(" ", "")
    library_compact = library_key.replace(" ", "")
    # Compact equality is the whole string, not a substring, so short titles
    # still cannot swallow a longer one ("one" vs "one more time").
    return len(chart_compact) >= 3 and chart_compact == library_compact


def score_pair(chart: ChartTrack, library: LibraryTrackRef) -> int | None:
    """Score one chart row against one library track, or None when they differ.

    Equal MusicBrainz recording ids are a strong match. Different recording
    ids are not a rejection: a remaster is a different recording of the same
    song, and Last.fm's id often points at only one of them.
    """
    mbid_match = bool(
        chart.mbid and library.recording_mbid and chart.mbid == library.recording_mbid
    )
    same_title = _titles_match(chart.title, library.title)
    if not mbid_match and not same_title:
        return None

    score = 0
    if mbid_match:
        score += 500
    if same_title:
        score += 200

    chart_noise = noise_flags(chart.title)
    library_noise = noise_flags(library.title) | noise_flags(library.version)
    score -= 40 * len(library_noise - chart_noise)
    score -= 15 * len(chart_noise - library_noise)
    if not library.version.strip() and not library_noise:
        score += 10
    if not library.available:
        score -= 80

    if chart.duration and library.duration:
        delta = abs(chart.duration - library.duration)
        if delta <= 3:
            score += 20
        elif delta <= 8:
            score += 8
        elif delta >= 30:
            score -= 15
    return score


def match_chart_to_library(
    chart: list[ChartTrack],
    library: list[LibraryTrackRef],
    *,
    limit: int,
) -> list[str]:
    """Return library keys in Last.fm popularity order, one copy of each track.

    :param chart: Top tracks, most popular first (``rank`` breaks ties).
    :param library: Tracks already known to belong to this artist.
    :param limit: Maximum number of matches.
    """
    if limit <= 0:
        return []

    used: set[str] = set()
    chosen: list[str] = []
    for chart_track in sorted(chart, key=lambda item: item.rank):
        if len(chosen) >= limit or not chart_track.title.strip():
            if len(chosen) >= limit:
                break
            continue
        best_key: str | None = None
        best_score: int | None = None
        best_version_length = 0
        for library_track in library:
            if not library_track.key or library_track.key in used:
                continue
            score = score_pair(chart_track, library_track)
            if score is None:
                continue
            version_length = len(library_track.version.strip())
            if best_score is None or score > best_score or (
                score == best_score and version_length < best_version_length
            ):
                best_score = score
                best_key = library_track.key
                best_version_length = version_length
        if best_key is None:
            continue
        used.add(best_key)
        chosen.append(best_key)
    return chosen

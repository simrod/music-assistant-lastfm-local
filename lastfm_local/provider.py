"""Music Assistant metadata provider: Last.fm top tracks matched to the library."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from music_assistant.models.metadata_provider import MetadataProvider
from music_assistant_models.config_entries import ConfigActionResult, ConfigEntry
from music_assistant_models.enums import ConfigEntryType, ExternalID, ProviderFeature
from music_assistant_models.errors import AuthenticationFailed

from .lastfm import LastFmClient, LastFmError
from .matching import (
    DEFAULT_CHART_REFRESH_DAYS,
    MAX_CHART_REFRESH_DAYS,
    MIN_CHART_REFRESH_DAYS,
    ChartTrack,
    LibraryTrackRef,
    chart_refresh_days,
    dedupe_chart_enabled,
    dedupe_chart_tracks,
    empty_chart_replaces,
    match_chart_to_library,
    pack_stored_chart,
    stored_chart_is_fresh,
    unpack_stored_chart,
)
from .play import install_into_frontend

if TYPE_CHECKING:
    from music_assistant.mass import MusicAssistant
    from music_assistant_models.media_items import Artist, Track


CONF_API_KEY = "api_key"
CONF_CHART_REFRESH_DAYS = "chart_refresh_days"
CONF_DEDUPE_CHART = "dedupe_chart"
CONF_CLEAR_CHARTS = "clear_charts"
CHART_CACHE_CATEGORY = 1
# Longer than any refresh interval, so raising the setting still finds the row,
# and an outage can serve it after the interval has elapsed. Cleanup keeps an
# allow_expired_cache row for 90 days past this.
CHART_CACHE_RETENTION_SECONDS = 365 * 24 * 60 * 60
# Music Assistant asks metadata providers for this many titles and does not
# pass the argument (see MusicDiscoveryMixin.get_artist_toptracks).
DEFAULT_LIMIT = 25

SUPPORTED_FEATURES = {ProviderFeature.ARTIST_TOPTRACKS}

_API_KEY_HELP = "https://www.last.fm/api/account/create"


def bundled_lastfm_api_key() -> str:
    """Return the server's built-in Last.fm key, or an empty string.

    Official Music Assistant builds ship a read-only key. Third-party builds
    leave it empty, and this provider then requires the option below.
    """
    try:
        from music_assistant.helpers.app_vars import app_var
    except ImportError:
        return ""
    try:
        value = app_var("lastfm_api_key")
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def _api_key_entry() -> ConfigEntry:
    bundled = bool(bundled_lastfm_api_key())
    description = (
        "Optional. Leave empty to use the key built into this Music Assistant server."
        if bundled
        else (
            "Required. A Last.fm API key with read access. "
            f"Create one at {_API_KEY_HELP}. No shared secret is used."
        )
    )
    return ConfigEntry(
        key=CONF_API_KEY,
        type=ConfigEntryType.SECURE_STRING,
        required=not bundled,
        advanced=bundled,
        label="Last.fm API key",
        description=description,
        help_link=_API_KEY_HELP,
        category="generic",
    )


def _chart_refresh_entry() -> ConfigEntry:
    return ConfigEntry(
        key=CONF_CHART_REFRESH_DAYS,
        type=ConfigEntryType.INTEGER,
        default_value=DEFAULT_CHART_REFRESH_DAYS,
        required=False,
        range=(MIN_CHART_REFRESH_DAYS, MAX_CHART_REFRESH_DAYS),
        label="Chart refresh (days)",
        description=(
            "Days to keep using a saved Last.fm chart before asking again. "
            "42 days is 6 weeks. If Last.fm is unreachable, the last saved chart is still used."
        ),
        category="generic",
    )


def _dedupe_chart_entry() -> ConfigEntry:
    return ConfigEntry(
        key=CONF_DEDUPE_CHART,
        type=ConfigEntryType.BOOLEAN,
        default_value=True,
        required=False,
        label="Collapse duplicate songs",
        description=(
            "After a chart is loaded, keep the highest-ranked row of each song. "
            "Case, punctuation, featuring credits, and a remaster label count as "
            "the same song. A live, remix, or acoustic listing stays. "
            "The saved chart is left as Last.fm returned it."
        ),
        category="generic",
    )


def _clear_charts_entry() -> ConfigEntry:
    return ConfigEntry(
        key=CONF_CLEAR_CHARTS,
        type=ConfigEntryType.ACTION,
        label="Clear saved charts",
        description=(
            "Delete every saved Last.fm chart for this provider. "
            "The next artist page asks Last.fm again. Library tracks stay."
        ),
        action=CONF_CLEAR_CHARTS,
        action_label="Clear saved charts",
        category="generic",
    )


class LastFmLocalProvider(MetadataProvider):
    """Artist top tracks from Last.fm, resolved only to in-library tracks."""

    def __init__(
        self,
        mass: MusicAssistant,
        manifest: Any,
        config: Any,
        supported_features: set[ProviderFeature],
    ) -> None:
        super().__init__(mass, manifest, config, supported_features)
        self._client: LastFmClient | None = None
        self._play_control_installed = False

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Return the provider options. Labels are inlined for out-of-tree installs.

        Music Assistant localizes ``strings.json`` only after
        ``build_translations.py`` has compiled it into the server catalog.
        A provider dropped into ``custom_providers`` never gets that compile
        step, so each entry also carries its own label and description.
        """
        return (
            _api_key_entry(),
            _chart_refresh_entry(),
            _dedupe_chart_entry(),
            _clear_charts_entry(),
        )

    async def handle_config_action(
        self, action: str
    ) -> tuple[ConfigEntry, ...] | ConfigActionResult | None:
        """Delete this provider's saved charts when the settings button is pressed."""
        if action != CONF_CLEAR_CHARTS:
            return await super().handle_config_action(action)
        # delete() matches the provider id exactly and includes persistent rows.
        # cache.clear() skips persistent rows unless asked, and matches the id
        # with a substring.
        await self.mass.cache.delete(
            None,
            category=CHART_CACHE_CATEGORY,
            provider=self.instance_id,
        )
        self.logger.info("Cleared saved Last.fm charts")
        return ConfigActionResult(
            message=(
                "Saved Last.fm charts were cleared. "
                "Open an artist again to fetch a new chart."
            )
        )

    async def handle_async_init(self) -> None:
        """Reject a missing key, and a key Last.fm itself refuses."""
        api_key = self._api_key()
        if not api_key:
            raise AuthenticationFailed(
                "A Last.fm API key is required. "
                f"Create one at {_API_KEY_HELP} and set it on this provider."
            )
        self._client = LastFmClient(self.mass.http_session, api_key)
        self._play_control_installed = self._install_play_control()
        try:
            await self._client.ping()
        except LastFmError as err:
            if err.auth_failed:
                raise AuthenticationFailed(str(err)) from err
            # Offline at startup is not fatal: the next artist page retries.
            self.logger.warning("Last.fm did not answer during setup: %s", err)

    async def get_artist_toptracks(self, artist: Artist, limit: int = DEFAULT_LIMIT) -> list[Track]:
        """Return this artist's library tracks in Last.fm popularity order.

        Music Assistant calls this only when none of the artist's music
        sources returned top tracks. Filesystem libraries do not, so this is
        the row local files would otherwise lack. Tracks Last.fm ranks that
        are not in the library are left out: they have nothing to play.
        """
        library_tracks = await self._library_tracks(artist)
        if not library_tracks:
            return []
        chart = self._dedupe_chart(await self._chart(artist, limit))
        if not chart:
            return []

        refs = [_library_ref(track) for track in library_tracks]
        by_key = {ref.key: track for ref, track in zip(refs, library_tracks, strict=True)}
        matched_keys = match_chart_to_library(chart, refs, limit=limit)
        matched = [by_key[key] for key in matched_keys if key in by_key]
        self.logger.debug(
            "Last.fm top tracks for %s: %d on the chart, %d in the library, %d matched",
            artist.name,
            len(chart),
            len(library_tracks),
            len(matched),
        )
        return matched

    async def get_artist_toptrack_titles(
        self, artist: Artist, limit: int = DEFAULT_LIMIT
    ) -> list[str]:
        """Return chart titles, including ones this library does not have."""
        chart = self._dedupe_chart(await self._chart(artist, limit))
        return [track.title for track in chart][:limit]

    async def get_diagnostics(self) -> dict[str, Any]:
        """Report whether a key is configured, never the key itself."""
        own_key = bool(self.config.get_value(CONF_API_KEY))
        return {
            "api_key_configured": bool(self._api_key()),
            "uses_bundled_key": not own_key and bool(bundled_lastfm_api_key()),
            "chart_refresh_days": self._chart_refresh_days(),
            "dedupe_chart": dedupe_chart_enabled(self.config.get_value(CONF_DEDUPE_CHART)),
            "play_control_installed": self._play_control_installed,
        }

    def _install_play_control(self) -> bool:
        """Add Play all and play-from-here on the artist Top Tracks row.

        The web app plays one track from that row. The script queues the chart
        from the chosen track. A failure here leaves that one-track play in
        place and does not stop the provider from loading.
        """
        try:
            from music_assistant_frontend import where
        except Exception as err:
            self.logger.warning("Top tracks play control was not added: %s", err)
            return False
        script_path = Path(__file__).with_name("toptracks_play.js")
        try:
            install_into_frontend(where(), script_path.read_text(encoding="utf-8"))
        except Exception as err:
            self.logger.warning(
                "Top tracks play control was not added to the web app: %s. "
                "The Top Tracks row plays one track at a time.",
                err,
            )
            return False
        self.logger.info(
            "Top Tracks play control is installed. Reload the web app, then Play all "
            "or a track's play button queues the chart from that point."
        )
        return True

    def _api_key(self) -> str:
        configured = self.config.get_value(CONF_API_KEY)
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
        return bundled_lastfm_api_key()

    def _chart_refresh_days(self) -> int:
        return chart_refresh_days(self.config.get_value(CONF_CHART_REFRESH_DAYS))

    def _dedupe_chart(self, chart: list[ChartTrack]) -> list[ChartTrack]:
        """Collapse duplicate songs when the settings switch is on.

        The saved chart is not rewritten. Turning the switch off uses the
        stored list on the next artist page.
        """
        if not dedupe_chart_enabled(self.config.get_value(CONF_DEDUPE_CHART)):
            return chart
        return dedupe_chart_tracks(chart)

    async def _library_tracks(self, artist: Artist) -> list[Track]:
        artists = getattr(getattr(self.mass, "music", None), "artists", None)
        getter = getattr(artists, "get_library_artist_tracks", None)
        if getter is None:
            self.logger.error(
                "This Music Assistant build has no get_library_artist_tracks; "
                "local top tracks cannot be matched."
            )
            return []
        try:
            tracks = await getter(artist.item_id)
        except Exception as err:
            # The library call can fail for one artist (missing row, provider
            # still loading). That artist's row stays empty; the provider stays up.
            self.logger.warning("Could not list library tracks for %s: %s", artist.name, err)
            return []
        return list(tracks or [])

    async def _chart(self, artist: Artist, limit: int) -> list[ChartTrack]:
        """Return the saved chart, refreshing it from Last.fm when it is due.

        The local copy is read first. Last.fm is contacted only when that copy
        is missing or older than the refresh interval. A failure, and an empty
        response that would erase a chart which already has tracks, leave the
        saved copy in place and return it.
        """
        limit = max(1, min(int(limit), 50))
        mbid = _external_id(artist, ExternalID.MB_ARTIST)
        cache_key = f"mbid:{mbid}|{limit}" if mbid else f"name:{artist.name}|{limit}"
        cached = await self.mass.cache.get(
            cache_key,
            provider=self.instance_id,
            category=CHART_CACHE_CATEGORY,
            allow_expired_cache=True,
        )
        unpacked = unpack_stored_chart(cached)
        stored: list[ChartTrack] | None = None
        fetched_at: int | None = None
        if unpacked is not None:
            stored, fetched_at = unpacked
        interval_seconds = self._chart_refresh_days() * 24 * 60 * 60
        now = int(time.time())
        if stored is not None and stored_chart_is_fresh(fetched_at, now, interval_seconds):
            return stored

        client = self._client
        if client is None:
            client = LastFmClient(self.mass.http_session, self._api_key())
            self._client = client
        try:
            chart = await client.artist_top_tracks(artist.name, mbid, limit)
        except LastFmError as err:
            self.logger.warning("Last.fm top tracks failed for %s: %s", artist.name, err)
            return stored if stored is not None else []

        if not chart and not empty_chart_replaces(stored):
            return stored or []

        await self.mass.cache.set(
            cache_key,
            pack_stored_chart(chart, now),
            expiration=CHART_CACHE_RETENTION_SECONDS,
            provider=self.instance_id,
            category=CHART_CACHE_CATEGORY,
            allow_expired_cache=True,
            persistent=True,
        )
        return chart


def _external_id(item: Any, external_id: ExternalID) -> str | None:
    getter = getattr(item, "get_external_id", None)
    if getter is None:
        return None
    try:
        value = getter(external_id)
    except Exception:
        return None
    return str(value) if value else None


def _library_ref(track: Track) -> LibraryTrackRef:
    """Adapt a library track. The listing is already limited to this artist."""
    key = getattr(track, "uri", None) or f"{track.provider}:{track.item_id}"
    duration = getattr(track, "duration", None)
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        duration = None
    return LibraryTrackRef(
        key=str(key),
        title=str(getattr(track, "name", "") or ""),
        version=str(getattr(track, "version", "") or ""),
        recording_mbid=_external_id(track, ExternalID.MB_RECORDING),
        duration=duration,
        available=bool(getattr(track, "available", True)),
    )

# Agent guide

Metadata provider for Music Assistant. It fills Artist Top Tracks for a local library from Last.fm's global chart. It does not stream, scrobble, or search Spotify, Tidal, or any other music source.

## Invariants

- `get_artist_toptracks` returns in-library `Track` objects only. A Last.fm title with no library copy is omitted. Inventing a provider item leaves a row that cannot play.
- Order is Last.fm popularity (`rank`), not play count inside Music Assistant and not library order.
- Do not resolve through streaming providers. `music_assistant.providers.lastfm_recommendations` already does that, and it is empty for a library that has no streaming source.
- Declare `ProviderFeature.ARTIST_TOPTRACKS` only. Do not add `LIBRARY_*` or `SEARCH`. This is not a music source.
- The directory name, the manifest `domain`, and the package name stay `lastfm_local`. Music Assistant imports `music_assistant.providers.<directory>`.
- `matching.py` and `lastfm.py` do not import `music_assistant` or `music_assistant_models`. `tests/test_package.py` locks that. `provider.py` is the only server module.
- Importing `lastfm_local` must not import Music Assistant. `setup` imports `provider.py` lazily.
- Never log the API key. Diagnostics report whether a key is set and the chart refresh interval, never the key.

## Where Music Assistant calls this

`ArtistsController.get_library_artist_toptracks` asks each music provider mapped on the artist. Metadata and plugin providers that implement the feature run only when every music provider answered and all of them returned nothing. The call is `get_artist_toptracks(library_artist)` on `MusicDiscoveryMixin`. The artist is a library item. Its tracks come from `mass.music.artists.get_library_artist_tracks(artist.item_id)`.

The controller's default limit is 25 and it does not pass that argument. Honor the `limit` parameter.

Music Assistant caches the assembled listing (`cached_listing` in the media controller). This provider reads its own saved chart first. The chart is kept in Music Assistant's cache as `{"fetched_at", "tracks"}`, keyed by artist and limit. While `fetched_at` is inside `chart_refresh_days` (default 42), Last.fm is not called. When the chart is missing or older than that, Last.fm is asked. A response with tracks replaces the saved chart. An empty response does not replace a chart that has tracks, and a failure is not stored: the saved chart is returned, or an empty list when there is none. The row is written with a 365-day expiration, `allow_expired_cache`, and `persistent`, so it outlives the refresh interval. Each assembly rematches the chart against the current library.

`strings.json` is compiled into the server catalog by `scripts/build_translations.py` only for in-tree providers. Config entries also set `label` and `description` so a copy dropped into `custom_providers` still has text. `ConfigEntry.__post_serialize__` keeps those values when no translation matches.

## Files

| Path | Role |
| --- | --- |
| `lastfm_local/__init__.py` | `setup(mass, manifest, config)` |
| `lastfm_local/manifest.json` | Provider manifest. `type` is `metadata`. |
| `lastfm_local/provider.py` | `LastFmLocalProvider`, config, cache, library lookup |
| `lastfm_local/lastfm.py` | HTTP client and `artist.getTopTracks` parsing |
| `lastfm_local/matching.py` | `title_key`, `score_pair`, `match_chart_to_library`, saved-chart envelope |
| `tests/` | Parser, matcher, import boundary |

## Matching rules

`title_key` is the song identity: accents, punctuation, featuring credits, and version decoration come off. A parenthetical that is part of the title (`Part 1`) stays.

`score_pair` returns `None` when the title differs and the MusicBrainz recording ids differ or are missing. Equal recording ids are a strong match. Unequal recording ids do not reject a title match, because a remaster is a different recording of the same song.

Version tags in `noise_flags` (live, demo, remix, and the rest of that table) cost points when the chart row did not ask for them. The plain copy wins. The tagged copy still wins when it is the only copy, or when the chart title carries the same tag. Duration is a tie break, not an identity.

## Extending

A new discovery method (`get_similar_tracks`, `get_artist_topalbums`) belongs on the provider, with a pure function next to `match_chart_to_library`, and must still return library items only. Add the feature to `SUPPORTED_FEATURES` or Music Assistant will not call it.

An API change stays in `lastfm.py`. Ranking changes stay in `matching.py` and get a test that names the library keys in chart order.

## Checks

```bash
python -m pytest
```

There is no Music Assistant checkout in this repo. Do not add the server as a test dependency to cover `provider.py`. Cover new ranking and parsing behavior in `tests/`.

# Agent guide

Metadata provider for Music Assistant. It fills Artist Top Tracks for a local library from Last.fm's global chart. It does not stream, scrobble, or search Spotify, Tidal, or any other music source.

## Invariants

- `get_artist_toptracks` returns in-library `Track` objects only. A Last.fm title with no library copy is omitted. Inventing a provider item leaves a row that cannot play.
- Order is Last.fm popularity (`rank`), not play count inside Music Assistant and not library order.
- Do not resolve through streaming providers. `music_assistant.providers.lastfm_recommendations` already does that, and it is empty for a library that has no streaming source.
- Declare `ProviderFeature.ARTIST_TOPTRACKS` only. Do not add `LIBRARY_*` or `SEARCH`. This is not a music source.
- The directory name, the manifest `domain`, and the package name stay `lastfm_local`. Music Assistant imports `music_assistant.providers.<directory>`.
- `matching.py`, `lastfm.py`, and `play.py` do not import `music_assistant` or `music_assistant_models`. `tests/test_package.py` locks that. `provider.py` is the only server module.
- Importing `lastfm_local` must not import Music Assistant. `setup` imports `provider.py` lazily.
- Never log the API key. Diagnostics report whether a key is set, the chart refresh interval, whether duplicate songs are collapsed, and whether the play control was written, never the key.
- The play control is best-effort. A failure to write it must not unload the provider and must not change `get_artist_toptracks`.

## Where Music Assistant calls this

`ArtistsController.get_library_artist_toptracks` asks each music provider mapped on the artist. Metadata and plugin providers that implement the feature run only when every music provider answered and all of them returned nothing. The call is `get_artist_toptracks(library_artist)` on `MusicDiscoveryMixin`. The artist is a library item. Its tracks come from `mass.music.artists.get_library_artist_tracks(artist.item_id)`.

The controller's default limit is 25 and it does not pass that argument. Honor the `limit` parameter.

Music Assistant caches the assembled listing (`cached_listing` in the media controller). This provider reads its own saved chart first. The chart is kept in Music Assistant's cache as `{"fetched_at", "tracks"}`, keyed by artist and limit. While `fetched_at` is inside `chart_refresh_days` (default 42), Last.fm is not called. When the chart is missing or older than that, Last.fm is asked. A response with tracks replaces the saved chart. An empty response does not replace a chart that has tracks, and a failure is not stored: the saved chart is returned, or an empty list when there is none. The row is written with a 365-day expiration, `allow_expired_cache`, and `persistent`, so it outlives the refresh interval and a general cache clear. Each assembly rematches the chart against the current library. When `dedupe_chart` is on (the default), that assembly first drops a later row whose song identity matches an earlier, higher-ranked row. Identity is `title_key` plus `noise_flags`, so case, punctuation, featuring credits, and a remaster label collapse, and a live, remix, or acoustic row stays. The saved chart is not rewritten. The switch is read on each call. The settings action `clear_charts` deletes this instance's rows in category `1` through `cache.delete`, which matches the instance id exactly and includes persistent rows. It does not remove library tracks.

`strings.json` is compiled into the server catalog by `scripts/build_translations.py` only for in-tree providers. Config entries also set `label` and `description` so a copy dropped into `custom_providers` still has text. `ConfigEntry.__post_serialize__` keeps those values when no translation matches.

## Playing the chart

The artist page queues one track from Top Tracks. Frontend 2.17 draws that as a `section` whose own toolbar title is `Top tracks`. The image copies `toptracks_play.js` to `lastfm-local-toptracks-play.js` in the directory `music_assistant_frontend.where()` returns, because the web server registers `GET /{filename}` only for files present when the process starts. On startup the provider writes that file again and inserts a classic script tag ahead of the app module in `index.html`. The script wraps `WebSocket` before the app's sendspin interceptor captures it.

`install()` keeps the charts for the request that is in flight. **Play all** is the first control in `.v-toolbar__append`. It sends `player_queues/play_media` with `option` `replace`, shuffle off, and no `start_item`, so the current queue is swapped for the chart. That is the album default. A track play leaves `option` as the app sent it. A collapsed section has the heading and no rows; Play all clicks the other append button once to open it, then retries the row play. A row play control (`.listitem-media-thumb.is-playable`, `button.listitem-mobile-play`, or `.track-number-play.is-playable`) queues from that track name through the end, with shuffle off. The name is the first text node of the inner `.v-list-item-title`. A later version or year span is not part of the name. The dots menu does not arm a chart play. Once visible names are a list the chart does not cover, the button is removed, so the newest-tracks fallback stays one track at a time. `createChartBook.match` stays a prefix match. The page's own chart list is separate and treats name order as irrelevant.

## Files

| Path | Role |
| --- | --- |
| `lastfm_local/__init__.py` | `setup(mass, manifest, config)` |
| `lastfm_local/manifest.json` | Provider manifest. `type` is `metadata`. |
| `lastfm_local/provider.py` | `LastFmLocalProvider`, config, cache, library lookup |
| `lastfm_local/lastfm.py` | HTTP client and `artist.getTopTracks` parsing |
| `lastfm_local/matching.py` | `title_key`, `score_pair`, `match_chart_to_library`, saved-chart envelope |
| `lastfm_local/play.py` | Copy `toptracks_play.js` into the web app and patch `index.html` |
| `lastfm_local/toptracks_play.js` | Browser script: queue the chart from a Top Tracks play button |
| `tests/` | Parser, matcher, play control, import boundary |

## Matching rules

`title_key` is the song identity: accents, punctuation, featuring credits, and version decoration come off. A parenthetical that is part of the title (`Part 1`) stays.

`score_pair` returns `None` when the title differs and the MusicBrainz recording ids differ or are missing. Equal recording ids are a strong match. Unequal recording ids do not reject a title match, because a remaster is a different recording of the same song.

Version tags in `noise_flags` (live, demo, remix, and the rest of that table) cost points when the chart row did not ask for them. The plain copy wins. The tagged copy still wins when it is the only copy, or when the chart title carries the same tag. Duration is a tie break, not an identity.

`dedupe_chart_tracks` runs before matching when the settings switch is on. It keeps the best-ranked row for each `title_key` and noise-tag set. Matching then picks one library file for each remaining row.

## Extending

A new discovery method (`get_similar_tracks`, `get_artist_topalbums`) belongs on the provider, with a pure function next to `match_chart_to_library`, and must still return library items only. Add the feature to `SUPPORTED_FEATURES` or Music Assistant will not call it.

An API change stays in `lastfm.py`. Ranking changes stay in `matching.py` and get a test that names the library keys in chart order.

## Checks

```bash
python -m pytest
```

There is no Music Assistant checkout in this repo. Do not add the server as a test dependency to cover `provider.py`. Cover new ranking and parsing behavior in `tests/`.

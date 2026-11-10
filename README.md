# Last.fm Local Top Tracks for Music Assistant

Music Assistant metadata provider that adds Last.fm top tracks for local files. On an artist page, the Top Tracks row follows Last.fm's global popularity instead of personal play counts, and every row is a track already in the library. No streaming service is required.

The built-in Last.fm provider can also fill that row, but it resolves each title through a streaming source. With only local files, that resolution has nothing to play. This provider reads the same chart and keeps the copies you already have.

It does not scrobble. Scrobbling stays on the Last.fm Scrobbler plugin.

## How a row is chosen

Music Assistant asks metadata providers for artist top tracks only when none of that artist's music sources returned any. A filesystem library does not supply top tracks, so this provider is the one that runs. If the artist is also linked to a streaming source that has its own top tracks, Music Assistant uses that source and does not call this provider.

For each call:

1. Load that artist's in-library tracks.
2. Read the saved Last.fm chart for this artist. Ask Last.fm `artist.getTopTracks` (MusicBrainz id first, artist name if that index is empty) only when no chart is saved or the saved one is older than the refresh interval, 42 days unless you change it. A response with tracks replaces the saved chart. An empty response keeps a saved chart that already has tracks. If Last.fm does not answer, the saved chart is used.
3. Walk the chart from most played to least. Keep the first library copy of each title, preferring the plain recording over a live, demo, or remix version. A live copy is used when it is the only one, or when the chart title itself is live.
4. Drop chart titles that are not in the library.

## Install

The provider folder must be named `lastfm_local`. Music Assistant loads `music_assistant.providers.lastfm_local`.

**Server checkout.** From a clone of [music-assistant/server](https://github.com/music-assistant/server):

```bash
ln -sfn "$PWD/lastfm_local" /path/to/server/music_assistant/providers/lastfm_local
```

Restart the server, then add **Last.fm Local Top Tracks** under Settings, Metadata Providers.

**Home Assistant custom providers.** Copy `lastfm_local/` to `/share/music_assistant/custom_providers/lastfm_local` and restart Music Assistant. This expects a loader that injects that directory into the server's `providers` package (for example [ma_custom_loader](https://github.com/neqq3/ma_custom_loader)). The official add-on does not load out-of-tree providers on its own.

**Docker Compose.** The official image has no setting for an extra provider. `Dockerfile` starts from `ghcr.io/music-assistant/server:latest` and copies `lastfm_local` into that image. Keep the Compose file on the machine that runs Music Assistant. It keeps host networking, the `/data` volume, and any music mounts. Replace `image:` with a build of this repo.

From GitHub, after this repo is pushed (use your owner, name, and branch):

```yaml
services:
  music-assistant-server:
    build:
      context: https://github.com/you/music-assistant-lastfm-local.git#main
    container_name: music-assistant-server
    restart: unless-stopped
    network_mode: host
    volumes:
      - ${USERDIR:-$HOME}/docker/music-assistant-server/data:/data/
      - /path/to/your/music:/media:ro
```

A checkout on the same machine can build the local directory instead:

```yaml
    build: /path/to/music-assistant-lastfm-local
```

Start it with:

```bash
docker compose up -d --build
```

That clones or reads this repo, pulls the official image, and copies the provider in. The existing `/data` directory keeps the library. Then add **Last.fm Local Top Tracks** under Settings, Metadata Providers. The provider is not enabled just because the image contains it.

A public GitHub repo needs no credentials. A private repo has to be cloneable from the Docker host. To pick up a newer Music Assistant release or a newer commit of this provider, run `docker compose build --pull` and then `docker compose up -d`. Change the `FROM` line to a fixed tag, such as `ghcr.io/music-assistant/server:2.10.0`, when `latest` is not what you want.

## Configuration

Last.fm requires an API key. Create one at <https://www.last.fm/api/account/create> (read access is enough; there is no shared secret and no account login).

On an official Music Assistant build the provider uses the server's built-in key when the field is left empty. Other builds have no built-in key, and the provider will not finish loading until a key is set.

Chart refresh is how many days a saved chart is reused before Last.fm is asked again. The default is 42 days (6 weeks). After that, a failure or an empty response still leaves a saved chart that has tracks in place.

## Tests

The chart parser and the matcher do not import Music Assistant.

```bash
python -m pytest
```

## License

MIT. See [LICENSE](LICENSE).

## Layout

`lastfm_local/` is the provider Music Assistant imports. `Dockerfile` copies that folder into the official server image. `matching.py` and `lastfm.py` have no server imports. `provider.py` is the Music Assistant glue. See `AGENTS.md` for the hooks a change has to keep.

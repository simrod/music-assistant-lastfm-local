# Official Music Assistant image, plus this provider in its providers package.
FROM ghcr.io/music-assistant/server:latest

COPY lastfm_local /tmp/lastfm_local
RUN set -eu \
 && site="$(python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
 && cp -a /tmp/lastfm_local "$site/music_assistant/providers/lastfm_local"

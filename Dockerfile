# Official Music Assistant image, plus this provider in its providers package.
# When the provider starts it also installs the Top Tracks play control
# into this image's web app. See README, "Playing the chart".
FROM ghcr.io/music-assistant/server:latest

COPY lastfm_local /tmp/lastfm_local
RUN set -eu \
 && site="$(python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
 && cp -a /tmp/lastfm_local "$site/music_assistant/providers/lastfm_local"

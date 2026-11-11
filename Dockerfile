# Official Music Assistant image, plus this provider in its providers package.
# The web server only routes files that already exist in the frontend
# directory when the process starts, so the play script is copied there
# during the build. The provider still patches index.html on startup.
# See README, "Playing the chart".
FROM ghcr.io/music-assistant/server:latest

COPY lastfm_local /tmp/lastfm_local
RUN set -eu \
 && site="$(python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')" \
 && cp -a /tmp/lastfm_local "$site/music_assistant/providers/lastfm_local" \
 && frontend="$(python -c 'import music_assistant_frontend; print(music_assistant_frontend.where())')" \
 && cp /tmp/lastfm_local/toptracks_play.js "$frontend/lastfm-local-toptracks-play.js"

"""Install the Top Tracks play control into Music Assistant's web app.

The artist page play button sends one track. Play all sends the chart with
enqueue option ``replace``, the same option an album play uses, so the
current queue is swapped for the chart. A track play still queues from that
track. This module copies a small script into the bundled web app and
references it from ``index.html``. The script file itself is
``toptracks_play.js``. Nothing here imports Music Assistant.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

SCRIPT_FILENAME = "lastfm-local-toptracks-play.js"

_TAG_RE = re.compile(
    r"[ \t]*<script src=\"/"
    + re.escape(SCRIPT_FILENAME)
    + r"(?:\?v=[^\"]*)?\"></script>\n?"
)


def script_tag(version: str) -> str:
    """Return the tag that loads this version of the play script."""
    return f'<script src="/{SCRIPT_FILENAME}?v={version}"></script>'


def _insert_before(html: str, index: int, tag: str) -> str:
    """Insert ``tag`` on its own line, using the indentation of the line at ``index``."""
    line_start = html.rfind("\n", 0, index) + 1
    indent = html[line_start:index]
    if indent.strip():
        indent = ""
        line_start = index
    return html[:line_start] + indent + tag + "\n" + html[line_start:]


def patch_index_html(html: str, version: str) -> str:
    """Return ``index.html`` with one play-script tag before the app script.

    An older tag for this script is removed first, so a new version replaces
    it. The tag is a classic script placed before the first ``<script>`` so it
    runs before the app module captures ``WebSocket``.
    """
    tag = script_tag(version)
    stripped = _TAG_RE.sub("", html)
    match = re.search(r"<script\b", stripped, flags=re.IGNORECASE)
    if match:
        return _insert_before(stripped, match.start(), tag)
    close = re.search(r"</body>", stripped, flags=re.IGNORECASE)
    if close:
        return _insert_before(stripped, close.start(), tag)
    return stripped + "\n" + tag + "\n"


def install_into_frontend(frontend_dir: Path, script_text: str) -> None:
    """Copy the play script next to ``index.html`` and reference it there.

    :param frontend_dir: Directory ``music_assistant_frontend.where()`` returns.
    :param script_text: Contents of ``toptracks_play.js``.
    :raises FileNotFoundError: The web app has no ``index.html`` here.
    :raises OSError: The web app files cannot be written.
    """
    frontend_dir = Path(frontend_dir)
    index_path = frontend_dir / "index.html"
    if not index_path.is_file():
        raise FileNotFoundError(index_path)
    version = hashlib.sha256(script_text.encode()).hexdigest()[:12]
    script_path = frontend_dir / SCRIPT_FILENAME
    if not script_path.is_file() or script_path.read_text(encoding="utf-8") != script_text:
        script_path.write_text(script_text, encoding="utf-8")
    html = index_path.read_text(encoding="utf-8")
    patched = patch_index_html(html, version)
    if patched != html:
        index_path.write_text(patched, encoding="utf-8")

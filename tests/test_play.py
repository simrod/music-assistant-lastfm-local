"""Play-control install tests. These do not import Music Assistant."""

import shutil
import subprocess
from pathlib import Path

import pytest
from lastfm_local.play import install_into_frontend, patch_index_html, script_tag

ROOT = Path(__file__).parents[1]
INDEX = """<!DOCTYPE html>
<html>
  <head>
    <script type="module" src="/assets/index-abc.js"></script>
  </head>
  <body>
    <div id="app"></div>
  </body>
</html>
"""


def test_patch_inserts_one_classic_script_before_the_app() -> None:
    patched = patch_index_html(INDEX, "abc123")
    tag = script_tag("abc123")
    assert patched.count(tag) == 1
    assert patched.index(tag) < patched.index('type="module"')
    assert patch_index_html(patched, "abc123") == patched


def test_patch_replaces_an_older_version() -> None:
    first = patch_index_html(INDEX, "old")
    second = patch_index_html(first, "new")
    assert script_tag("old") not in second
    assert second.count(script_tag("new")) == 1
    assert second.count("<script") == 2


def test_patch_without_a_script_tag_lands_before_body() -> None:
    html = "<html><body><div id=\"app\"></div></body></html>"
    patched = patch_index_html(html, "abc")
    assert patched.index(script_tag("abc")) < patched.lower().index("</body>")


def test_install_writes_the_script_and_is_idempotent(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_text(INDEX, encoding="utf-8")
    script = (ROOT / "lastfm_local" / "toptracks_play.js").read_text(encoding="utf-8")
    install_into_frontend(tmp_path, script)
    install_into_frontend(tmp_path, script)
    assert (tmp_path / "lastfm-local-toptracks-play.js").read_text(encoding="utf-8") == script
    html = index.read_text(encoding="utf-8")
    assert html.count("lastfm-local-toptracks-play.js") == 1
    assert html.index("lastfm-local-toptracks-play.js") < html.index('type="module"')


def test_install_requires_index_html(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        install_into_frontend(tmp_path, "var x = 1;\n")


def test_play_script_queues_the_chart_from_the_clicked_track() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    completed = subprocess.run(
        [node, str(Path(__file__).with_name("toptracks_play.test.mjs"))],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

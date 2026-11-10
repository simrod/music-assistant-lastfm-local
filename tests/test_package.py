"""The installable package must stay importable without Music Assistant."""

import ast
import sys
from pathlib import Path


def test_package_import_does_not_pull_in_music_assistant() -> None:
    before = {
        name
        for name in sys.modules
        if name == "music_assistant" or name.startswith("music_assistant.")
    }
    import lastfm_local

    after = {
        name
        for name in sys.modules
        if name == "music_assistant" or name.startswith("music_assistant.")
    }
    assert after == before
    assert callable(lastfm_local.setup)


def test_provider_module_is_the_only_music_assistant_import() -> None:
    """matching.py and lastfm.py stay free of the server, so pytest needs no server checkout."""
    root = Path(__file__).parents[1] / "lastfm_local"
    for path in (root / "matching.py", root / "lastfm.py", root / "__init__.py"):
        tree = ast.parse(path.read_text())
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert not any(name.startswith("music_assistant") for name in imported), path.name

    provider = ast.parse((root / "provider.py").read_text())
    provider_imports = [
        node.module or ""
        for node in ast.walk(provider)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("music_assistant")
    ]
    assert provider_imports

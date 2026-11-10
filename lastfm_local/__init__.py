"""Last.fm top tracks for a local Music Assistant library.

Music Assistant loads ``setup`` from this module. Importing the package does
not import Music Assistant, so the chart parser and the matcher can be tested
on their own.
"""

from __future__ import annotations

from typing import Any


async def setup(mass: Any, manifest: Any, config: Any) -> Any:
    """Create the provider instance for this configuration."""
    from .provider import SUPPORTED_FEATURES, LastFmLocalProvider

    return LastFmLocalProvider(mass, manifest, config, SUPPORTED_FEATURES)

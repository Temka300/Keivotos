"""First-run default Files library beside the program.

On the very first run of a fresh install, create a ``library`` folder next to the
executable and register it as a visible Files source, so the user has somewhere
to drop videos, audio, and images immediately. This is offered exactly once: the
lifecycle caller gates it on a config flag, and this function additionally
refuses to touch a base that already has folders, so an existing library is
never disturbed and a deliberately removed folder is never recreated.

Shared, always-on behavior of the Files base — no Danbooru dependency. The
folder is left empty; the browse endpoint indexes it lazily on first open.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from files_base import sources

logger = logging.getLogger(__name__)

DEFAULT_LIBRARY_NAME = "Library"


def install_default_library(
    user_conn: sqlite3.Connection,
    library_dir: Path,
    *,
    forbidden_paths: list[Path],
    display_name: str = DEFAULT_LIBRARY_NAME,
) -> sources.Source | None:
    """Create and register the default library — only for a brand-new base.

    Returns the new :class:`~files_base.sources.Source`, or ``None`` when the
    base already has any registered folder (an existing user is never given a
    default) or the target path is unsafe to register.
    """
    sources.ensure_sources_schema(user_conn)
    # An existing user already has their own folders; never inject a default.
    if sources.list_sources(user_conn):
        return None
    # Create the folder before the safety check, which requires it to exist.
    library_dir.mkdir(parents=True, exist_ok=True)
    reason = sources.unsafe_source_reason(library_dir, forbidden_paths)
    if reason is not None:
        logger.warning("Not registering default library %s: %s", library_dir, reason)
        return None
    return sources.register_source(user_conn, str(library_dir), display_name, role="files")

"""Basic local Video: shared Files discovery, no separate durable playback state."""
from pathlib import Path
from module_descriptor import ModuleDescriptor


def _routers():
    from modules.video.router import router
    return [router]


def adopt(source_id: str) -> dict:
    from database import get_user_db
    from files_base import sources
    with get_user_db() as connection:
        if sources.get_source(connection, source_id) is None:
            raise ValueError("Unknown folder")
        sources.update_source(connection, source_id, role="video")
    return {"source_id": source_id, "role": "video"}


def release(source_id: str, forget: bool = False) -> dict:
    from database import get_user_db
    from files_base import sources
    with get_user_db() as connection:
        source = sources.get_source(connection, source_id)
        if source is None or source.role != "video":
            raise ValueError("Unknown Video folder")
        if forget:
            sources.remove_source(connection, source_id)
        else:
            sources.update_source(connection, source_id, role="files")
    return {"source_id": source_id, "role": "files", "forgotten": forget}


def descriptor(suite_home: Path, version: str) -> ModuleDescriptor:
    return ModuleDescriptor(
        slug="video", name="Video", description="Watch videos from your local folders.",
        home=suite_home / "modules" / "video", database=suite_home / "base" / "files.sqlite",
        credentials=None, api_prefix="/api/video", log_prefix="video",
        user_agent=f"Keivotos/{version} (Video)", disableable=True, is_base=False,
        router_provider=_routers, adopt_hook=adopt, release_hook=release,
    )

"""Danbooru's historical process entry points, loaded without credential I/O."""
from collections.abc import Callable


def dispatch_helper(
    arguments: list[str], *, load_configuration: Callable[..., object],
    run_helper: Callable[[str, list[str]], int],
) -> int | None:
    if arguments == ["--credential-worker"]:
        from modules.danbooru.credentials import _VAULT_WORKER

        exec(_VAULT_WORKER, {"__name__": "__main__"})
        return 0
    if arguments[:1] == ["--pipeline"]:
        load_configuration(migrate_legacy_home=True)
        return run_helper("danbooru_gallery_dl.py", arguments[1:])
    return None

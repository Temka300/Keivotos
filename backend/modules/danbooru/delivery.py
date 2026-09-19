"""Danbooru-owned source/frozen delivery requirements, even when disabled."""
from delivery_contract import DeliveryContribution, PortableTool


def contribution(target: str) -> DeliveryContribution:
    linux = target == 'linux'
    return DeliveryContribution(
        helpers=(("Danbooru pipeline", "scripts/danbooru_gallery_dl.py"),),
        hidden_imports=("modules.danbooru.pipeline",) + (("keyring.backends.SecretService",) if linux else ()),
        collect_packages=("secretstorage",) if linux else (),
        metadata_packages=("keyring",) if linux else (),
        tools=(PortableTool("gallery-dl", "--version", "packaging/windows/gallery_dl_entry.py"),),
        configured_paths=(("Library", "DATA_ROOT"), ("Metadata", "METADATA_DIR"), ("gallery-dl", "GALLERY_DL_DIR")),
    )

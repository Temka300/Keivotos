"""Static delivery declarations; no configuration, credentials or build imports."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PortableTool:
    name: str
    version_flag: str
    entry_script: str | None = None


@dataclass(frozen=True)
class DeliveryContribution:
    helpers: tuple[tuple[str, str], ...] = ()
    hidden_imports: tuple[str, ...] = ()
    collect_packages: tuple[str, ...] = ()
    metadata_packages: tuple[str, ...] = ()
    tools: tuple[PortableTool, ...] = ()
    configured_paths: tuple[tuple[str, str], ...] = ()

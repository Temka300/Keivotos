"""Static registry of suite surfaces and optional modules."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from module_descriptor import ModuleDescriptor
try:
    from modules.danbooru import descriptor as danbooru_descriptor
    from modules.danbooru.delivery import contribution as danbooru_delivery
    from modules.danbooru.helpers import dispatch_helper as danbooru_helper
except ModuleNotFoundError as exc:
    if exc.name != "modules.danbooru":
        raise
    danbooru_descriptor = None
    danbooru_helper = None
    danbooru_delivery = None
from modules.files import descriptor as files_descriptor
try:
    from modules.video import descriptor as video_descriptor
except ModuleNotFoundError as exc:
    if exc.name != "modules.video":
        raise
    video_descriptor = None


# One import/factory entry is the registration boundary for each module.
_DESCRIPTOR_FACTORIES = (
    files_descriptor,
) + ((danbooru_descriptor,) if danbooru_descriptor is not None else ()) + ((video_descriptor,) if video_descriptor is not None else ())


_DELIVERY_PROVIDERS = (danbooru_delivery,) if danbooru_delivery is not None else ()


def delivery_contributions(target: str):
    return tuple(provider(target) for provider in _DELIVERY_PROVIDERS)


_HELPER_HANDLERS = (danbooru_helper,) if danbooru_helper is not None else ()


def dispatch_helper(
    arguments: list[str], *, load_configuration: Callable[..., object],
    run_helper: Callable[[str, list[str]], int],
) -> int | None:
    """Route explicit helper commands without loading module runtime services.

    None means unclaimed; zero is a successfully handled command. Helpers are
    process entry points, independent of UI enablement and app startup.
    """
    for handler in _HELPER_HANDLERS:
        result = handler(arguments, load_configuration=load_configuration, run_helper=run_helper)
        if result is not None:
            return result
    return None


class ModuleRegistry:
    def __init__(self, descriptors: tuple[ModuleDescriptor, ...]) -> None:
        by_slug = {descriptor.slug: descriptor for descriptor in descriptors}
        if len(by_slug) != len(descriptors):
            raise ValueError("Module descriptor slugs must be unique")
        bases = [descriptor for descriptor in descriptors if descriptor.is_base]
        if len(bases) != 1 or bases[0].disableable:
            raise ValueError("The registry requires exactly one non-disableable base")
        self._descriptors = descriptors
        self._by_slug = by_slug
        self._base = bases[0]

    def __iter__(self) -> Iterator[ModuleDescriptor]:
        return iter(self._descriptors)

    def __len__(self) -> int:
        return len(self._descriptors)

    @property
    def base(self) -> ModuleDescriptor:
        return self._base

    def get(self, slug: str) -> ModuleDescriptor | None:
        return self._by_slug.get(slug)

    def require(self, slug: str) -> ModuleDescriptor:
        descriptor = self.get(slug)
        if descriptor is None:
            raise KeyError(f"Unknown module descriptor: {slug}")
        return descriptor

    def optional(self) -> tuple[ModuleDescriptor, ...]:
        return tuple(descriptor for descriptor in self if descriptor.disableable)

    def replacing(self, replacement: ModuleDescriptor) -> "ModuleRegistry":
        if replacement.slug not in self._by_slug:
            raise KeyError(f"Unknown module descriptor: {replacement.slug}")
        return ModuleRegistry(
            tuple(
                replacement if descriptor.slug == replacement.slug else descriptor
                for descriptor in self
            )
        )


def build_registry(suite_home: Path, version: str) -> ModuleRegistry:
    resolved_home = suite_home.expanduser().resolve(strict=False)
    return ModuleRegistry(
        tuple(factory(resolved_home, version) for factory in _DESCRIPTOR_FACTORIES)
    )


# Catalog entries are discoverable plans, not installed/runnable descriptors.
# Promote an entry to an actual descriptor when its implementation is delivered.
PLANNED_MODULES = (
    {"id": "video", "name": "Video", "experimental": False},
    {"id": "manga", "name": "Manga", "experimental": False},
    {"id": "youtube", "name": "YouTube", "experimental": True},
)

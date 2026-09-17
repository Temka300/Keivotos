"""Static registry of suite surfaces and optional modules."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from module_descriptor import ModuleDescriptor
try:
    from modules.danbooru import descriptor as danbooru_descriptor
except ModuleNotFoundError as exc:
    if exc.name != "modules.danbooru":
        raise
    danbooru_descriptor = None
from modules.files import descriptor as files_descriptor


# One import/factory entry is the registration boundary for each module.
_DESCRIPTOR_FACTORIES = (
    files_descriptor,
) + ((danbooru_descriptor,) if danbooru_descriptor is not None else ())


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

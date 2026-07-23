import FilesView from '../components/FilesView.svelte';
import DanbooruSurface from './danbooru/DanbooruSurface.svelte';

const SURFACES = {
  files: FilesView,
  danbooru: DanbooruSurface,
} as const;

export function surfaceComponent(slug: string) {
  return SURFACES[slug as keyof typeof SURFACES] ?? FilesView;
}

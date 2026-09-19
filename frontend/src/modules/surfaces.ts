import FilesView from '../components/FilesView.svelte';

// Keep surfaces separate from actions so a component can import the action
// registry without importing its own constructor during module initialization.
const contributions = import.meta.glob<typeof FilesView>('./*/surface.ts', {
  eager: true,
  import: 'default',
});
const SURFACES: Record<string, typeof FilesView> = Object.fromEntries(
  Object.entries(contributions).map(([path, component]) => [path.split('/')[1], component]),
);

export function surfaceComponent(slug: string) {
  return SURFACES[slug] ?? FilesView;
}

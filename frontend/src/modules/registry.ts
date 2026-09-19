import { activeModule } from '../lib/suiteStores';

export interface DrawerAction {
  id: string;
  label: string;
  iconSrc: string;
  run: () => void;
}

export interface ModuleUiDescriptor {
  slug: string;
  iconSrc: string | null;
  drawerActions: DrawerAction[];
  activate?: () => void;
}

// Eager discovery preserves synchronous activation and existing store initialization.
// Each installed owner contributes its own actions; the registry names no module.
const contributions = import.meta.glob<ModuleUiDescriptor>('./*/ui.ts', {
  eager: true,
  import: 'default',
});
const UI_DESCRIPTORS: Record<string, ModuleUiDescriptor> = Object.fromEntries(
  Object.values(contributions).map((descriptor) => [descriptor.slug, descriptor]),
);

const FALLBACK_UI: ModuleUiDescriptor = {
  slug: 'unknown',
  iconSrc: null,
  drawerActions: [],
};

export function moduleUi(slug: string): ModuleUiDescriptor {
  return UI_DESCRIPTORS[slug] ?? { ...FALLBACK_UI, slug };
}

export function activateModule(slug: string): void {
  moduleUi(slug).activate?.();
  activeModule.set(slug);
}

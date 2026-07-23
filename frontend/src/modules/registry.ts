import {
  activeCollectionId,
  activeModule,
  selectedImageId,
  viewMode,
} from '../lib/stores';

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

const UI_DESCRIPTORS: Record<string, ModuleUiDescriptor> = {
  files: {
    slug: 'files',
    iconSrc: null,
    drawerActions: [],
  },
  danbooru: {
    slug: 'danbooru',
    iconSrc: '/logo.svg',
    activate: () => {
      activeCollectionId.set(null);
      selectedImageId.set(null);
      viewMode.set('home');
    },
    drawerActions: [
      {
        id: 'profile',
        label: 'Profile',
        iconSrc: '/profile-avatar.svg',
        run: () => {
          activeModule.set('danbooru');
          activeCollectionId.set(null);
          selectedImageId.set(null);
          viewMode.set('profile');
        },
      },
    ],
  },
};

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

import { activeCollectionId, selectedImageId, viewMode } from './stores';
import { activeModule } from '../../lib/suiteStores';
import type { ModuleUiDescriptor } from '../registry';

const descriptor: ModuleUiDescriptor = {
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
  };

export default descriptor;

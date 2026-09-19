import { MODULE_NAME } from './identity';
import component from './Settings.svelte';
import type { SettingsContribution } from '../../lib/settingsTypes';

const contribution: SettingsContribution = {
  group: { id: 'danbooru', label: MODULE_NAME, module: 'danbooru' },
  order: 2,
  component,
  sections: [
    { id: 'account', group: 'danbooru', label: 'Account', icon: 'database' },
    { id: 'browsing', group: 'danbooru', label: 'Browsing', icon: 'window' },
    { id: 'display', group: 'danbooru', label: 'Display', icon: 'palette' },
    { id: 'library', group: 'danbooru', label: 'Library', icon: 'folder' },
    { id: 'maintenance', group: 'danbooru', label: 'Advanced', icon: 'shield' },
  ],
  searchItems: [
    { id: 'danbooru-access', section: 'account', label: 'Danbooru access', description: 'Manage encrypted credentials.', keywords: ['username', 'api key', 'credentials', 'connection'] },
    { id: 'startup-view', section: 'browsing', label: 'Startup view', description: `Choose which ${MODULE_NAME} page opens first.`, keywords: ['home', 'browse', 'last page', 'launch', 'gallery'] },
    { id: 'home-layout', section: 'browsing', label: 'Home layout', description: 'Use the new discovery dashboard or restore the preserved classic Home.', keywords: ['home', 'classic', 'legacy', 'old design', 'discovery', 'dashboard'] },
    { id: 'rating-filter', section: 'browsing', label: 'Default rating', description: 'Choose the rating used for normal browsing.', keywords: ['general', 'sensitive', 'questionable', 'explicit', 'unrated'] },
    { id: 'browse-sort', section: 'browsing', label: 'Browse sort', description: 'Choose the persisted image order.', keywords: ['date', 'downloaded', 'score', 'views', 'name', 'size'] },
    { id: 'page-size', section: 'browsing', label: 'Images per page', description: 'Choose the normal grid page size.', keywords: ['pagination', '10', '20', '30', '50', 'all'] },
    { id: 'sidebar', section: 'browsing', label: 'Sidebar recovery', description: 'Mirror the draggable Browse and Tags edge grip state.', keywords: ['folders', 'visible', 'navigation', 'grip', 'handle', 'draggable'] },
    { id: 'heart-spam', section: 'browsing', label: 'Heart Spam', description: 'Show the playful heart action in ImageDetail.', keywords: ['image detail', 'button'] },
    { id: 'artist-notifications', section: 'browsing', label: 'Artist notifications', description: 'Check followed artists while the app is open.', keywords: ['danbooru', 'followed', 'polling', 'bell', 'timer', 'interval', 'manual check'] },
    { id: 'duplicate-review', section: 'browsing', label: 'Duplicate review', description: 'Choose which duplicate groups to review.', keywords: ['same folder', 'different folders', 'review'] },
    { id: 'gallery-card-size', section: 'display', label: 'Gallery card size', description: 'Set the image-grid scale.', keywords: ['small', 'medium', 'large', 'huge', 'gigantic', 'absurd'] },
    { id: 'image-fit', section: 'display', label: 'Image fit', description: 'Crop cards or preserve the full image.', keywords: ['crop', 'contain', 'fill'] },
    { id: 'media-playback', section: 'display', label: 'Animated media', description: 'Control GIF and video playback.', keywords: ['autoplay', 'hover', 'never', 'always', 'gif', 'video'] },
    { id: 'tag-banner', section: 'display', label: 'Tag banner height', description: 'Set tag and artist banner height.', keywords: ['low', 'tall', 'huge', 'artist'] },
    { id: 'library-health', section: 'library', label: 'Library health', description: 'See indexed folders, images, and scan state.', keywords: ['status', 'count', 'index'] },
    { id: 'rescan', section: 'library', label: 'Re-scan library', description: 'Incrementally reconcile the local index.', keywords: ['sync', 'sqlite', 'changed', 'removed'] },
    { id: 'storage-location', section: 'library', label: 'Generated metadata location', description: 'See where databases, sidecars, and derived files live.', keywords: ['documents', 'portable', 'data', 'sidecars', 'sqlite'] },
    { id: 'import-pipeline', section: 'library', label: 'Import pipeline', description: 'Run the four resumable library import phases.', keywords: ['discover', 'enrich', 'metadata', 'finalize'] },
    { id: 'automation', section: 'library', label: 'Local library watcher', description: 'Detect new or changed files without contacting Danbooru.', keywords: ['automatic', 'watcher', 'sidecar', 'interval', 'local'] },
    { id: 'clean-sidecars', section: 'maintenance', label: 'Clean orphan sidecars', description: 'Remove metadata whose reachable media file is gone.', keywords: ['cleanup', 'orphan', 'metadata'] },
    { id: 'folder-sidecars', section: 'maintenance', label: 'Folder sidecars', description: 'Delete the central sidecar metadata for a registered folder.', keywords: ['sidecar', 'delete', 'remove', 'folder', 'metadata', 'un-index'] },
    { id: 'rebuild', section: 'maintenance', label: 'Rebuild database', description: 'Recover the regenerable SQLite index from sidecars.', keywords: ['recovery', 'sqlite', 'repair'] },
  ],
};

export default contribution;

const BASE = '/api';
const THUMBNAIL_VERSION = 'v4';

export interface ImageSummary {
  id: number;
  file_id: number;
  thumbnail_token: string;
  filename: string;
  folder: string | null;
  ext: string | null;
  downloaded_at: string | null;
  created_at: string | null;
  width: number | null;
  height: number | null;
  score: number | null;
  rating: string | null;
  danbooru_post_id: number | null;
  is_favorite: boolean;
  favorite_added_at: string | null;
  favorite_pinned_at: string | null;
  collection_added_at: string | null;
  collection_pinned_at: string | null;
}

export interface PaginatedImages {
  images: ImageSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface TagInfo {
  name: string;
  category: string;
  count: number;
  favorite_added_at?: string | null;
  pinned_at?: string | null;
}

export interface TagWikiTextPart {
  text: string;
  tag: string | null;
  post_id: number | null;
}

export interface TagWikiTextLine {
  parts: TagWikiTextPart[];
}

export interface TagWikiExample {
  danbooru_post_id: number;
  local_post_id: number | null;
  file_id: number | null;
  thumbnail_token: string | null;
  filename: string | null;
  folder: string | null;
  ext: string | null;
  width: number | null;
  height: number | null;
  score: number | null;
  rating: string | null;
  post_url: string | null;
  created_at: string | null;
}

export interface TagWikiSection {
  title: string;
  paragraphs: TagWikiTextLine[];
  items: TagWikiTextLine[];
}

export interface ArtistUrl {
  url: string;
  is_active: boolean;
}

export interface TagWikiInfo {
  tag_name: string;
  title: string;
  other_names: string[];
  description: TagWikiTextLine[];
  examples: TagWikiExample[];
  post_references: TagWikiExample[];
  sections: TagWikiSection[];
  aliases: string[];
  implications: string[];
  artist_id: number | null;
  artist_name: string | null;
  artist_group_name: string | null;
  artist_urls: ArtistUrl[];
  available: boolean;
  cached_at: string | null;
  error: string | null;
}

export interface ArtistFollowInfo {
  tag_name: string;
  tag_category: string;
  display_name: string | null;
  local_count: number;
  added_at: string;
  last_checked_at: string | null;
  notification_initialized_at: string | null;
  last_seen_danbooru_post_id: number | null;
  unseen_count: number;
  profile_post: TagWikiExample | null;
  posts: TagWikiExample[];
}

export interface ArtistFollowCheckResult {
  follow: ArtistFollowInfo;
  discovered_count: number;
}

export interface ArtistProfileAsset {
  id: number;
  tag_name: string;
  platform: 'twitter' | 'pixiv';
  asset_kind: 'avatar' | 'banner';
  source_profile_url: string;
  source_url: string;
  file_url: string;
  width: number;
  height: number;
  captured_at: string;
}

export interface ArtistProfileArchiveResult {
  assets: ArtistProfileAsset[];
  saved_count: number;
  unchanged_count: number;
  notices: string[];
  errors: string[];
}

export interface ArtistProfileBulkArchiveResult {
  checked_artists: number;
  saved_count: number;
  unchanged_count: number;
  errors: string[];
}

export interface HomeCoverCandidate {
  post_id: number;
  file_id: number;
  thumbnail_token: string;
  width: number | null;
  height: number | null;
}

export interface HomeTagInfo {
  name: string;
  category: string;
  count: number;
  cover_post_id: number | null;
  cover_file_id: number | null;
  thumbnail_token: string | null;
  cover_candidates: HomeCoverCandidate[];
}

export interface HomeTags {
  featured: HomeTagInfo[];
  groups: Record<string, HomeTagInfo[]>;
}

export interface HomeImageRailItem {
  id: number;
  file_id: number;
  thumbnail_token: string;
  filename: string;
  folder: string | null;
  ext: string | null;
  width: number | null;
  height: number | null;
  score: number | null;
  rating: string | null;
  tag_name: string | null;
  tag_category: string | null;
  is_favorite: boolean;
}

export interface HomeImageRail {
  key: string;
  label: string;
  items: HomeImageRailItem[];
}

export interface HomeImageRails {
  rails: HomeImageRail[];
}

export interface DailyChallengeImage {
  id: number;
  file_id: number;
  thumbnail_token: string;
  filename: string;
  folder: string | null;
  ext: string | null;
  width: number | null;
  height: number | null;
  score: number | null;
  rating: string | null;
  created_at: string | null;
  danbooru_post_id: number | null;
}

export interface DailyChallengeOption {
  name: string;
  count: number;
}

export interface DailyChallengeClues {
  copyrights: string[];
  artists: string[];
  general: string[];
  meta: string[];
  folder: string | null;
  rating: string | null;
  score: number | null;
  year: number | null;
}

export interface DailyChallenge {
  date: string;
  challenge_id: string;
  image: DailyChallengeImage;
  answer_tag: string;
  options: DailyChallengeOption[];
  clues: DailyChallengeClues;
  total_candidates: number;
}

export interface FavoriteTagCombo {
  id: number;
  name: string;
  tags: string[];
  added_at: string;
}

export interface PaginatedTags {
  tags: TagInfo[];
  total: number;
  offset: number;
  limit: number;
}

export interface PopularityPeriod {
  period: string;
  label: string;
  start_date: string;
  end_date: string;
  image_count: number;
  popularity: number;
  average_score: number;
  best_score: number;
}

export interface TimelapseFrames {
  images: ImageSummary[];
  total: number;
  sampled: number;
  start_date: string | null;
  end_date: string | null;
}

export interface RelatedImageInfo {
  danbooru_post_id: number;
  local_post_id: number | null;
  file_id: number | null;
  thumbnail_token: string | null;
  filename: string | null;
  folder: string | null;
  ext: string | null;
  width: number | null;
  height: number | null;
  score: number | null;
  rating: string | null;
  post_url: string | null;
  created_at: string | null;
}

export interface ImageRelations {
  parent: RelatedImageInfo | null;
  siblings: RelatedImageInfo[];
  children: RelatedImageInfo[];
  has_metadata: boolean;
}

export interface ImageDetail {
  id: number;
  file_id: number;
  thumbnail_token: string;
  filename: string;
  folder: string | null;
  ext: string | null;
  path: string;
  size: number | null;
  local_md5: string | null;
  downloaded_at: string | null;
  width: number | null;
  height: number | null;
  score: number | null;
  rating: string | null;
  danbooru_post_id: number | null;
  post_url: string | null;
  source_url: string | null;
  created_at: string | null;
  updated_at: string | null;
  tags: Record<string, string[]>;
  removed_tags: string[];
  user_tags: Record<string, string[]>;
  is_favorite: boolean;
  favorite_added_at: string | null;
  favorite_pinned_at: string | null;
  view_count: number;
  heart_spam_count: number;
  first_viewed_at: string | null;
  last_viewed_at: string | null;
  collections: CollectionInfo[];
  relations: ImageRelations;
}

export interface FolderInfo {
  name: string;
  selector: string;
  count: number;
  path: string | null;
  root_id?: string | null;
  registered: boolean;
}

export interface FolderRelocateResult {
  status: 'relocated';
  name: string;
  selector: string;
  path: string;
  root_id: string;
  files_updated: number;
  sync: string;
  active_tool_id?: string | null;
}

export type FolderRemovalMode = 'unindex_only' | 'delete_sidecars';

export interface FolderRemovalPreview {
  name: string;
  path: string;
  root_id: string;
  indexed_files: number;
  sidecar_files: number;
  sidecar_bytes: number;
  external_images_affected: number;
  sidecar_history_preserved: boolean;
}

export interface FolderRemovalResult {
  status: string;
  name: string;
  mode: FolderRemovalMode;
  files_removed: number;
  sidecar_files_removed: number;
  sidecar_bytes_removed: number;
  external_images_affected: number;
  sidecar_history_preserved: boolean;
}

export interface UserSetting {
  key: string;
  value: string;
}

export interface CollectionPreviewItem {
  file_id: number;
  thumbnail_token: string | null;
  filename: string | null;
  ext: string | null;
  width: number | null;
  height: number | null;
}

export interface CollectionInfo {
  id: number;
  name: string;
  description: string;
  created_at: string;
  pinned_at: string | null;
  image_count: number;
  preview_ids: number[];
  preview_items: CollectionPreviewItem[];
  item_added_at?: string | null;
  item_pinned_at?: string | null;
}

export interface Stats {
  total_images: number;
  total_tags: number;
  total_folders: number;
  total_favorites: number;
  total_collections: number;
  total_image_views: number;
  seen_images: number;
  total_storage_bytes: number;
  total_user_tags: number;
  total_favorite_tags: number;
  total_followed_artists: number;
  total_collection_items: number;
  average_score: number | null;
  best_score: number | null;
  downloaded_from: string | null;
  downloaded_to: string | null;
  first_viewed_at: string | null;
  last_viewed_at: string | null;
  profile_avatar_file_id: number | null;
  profile_avatar_token: string | null;
  profile_banner_file_id: number | null;
  profile_banner_token: string | null;
}

async function get<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
  signal?: AbortSignal,
): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v));
    }
  }
  const res = await fetch(url.toString(), { signal });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function apiError(res: Response): Promise<Error> {
  let detail = '';
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') detail = data.detail;
    else if (data?.detail) detail = JSON.stringify(data.detail);
  } catch {
    // Non-JSON error body; fall back to the status line.
  }
  return new Error(detail || `API ${res.status}: ${res.statusText}`);
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function del<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
  }
  const res = await fetch(url.toString(), { method: 'DELETE' });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

export function thumbnailUrl(fileId: number, size?: number, token?: string): string {
  const params = new URLSearchParams();
  params.set('tv', THUMBNAIL_VERSION);
  const tier = !size || size <= 300 ? 300 : size <= 600 ? 600 : 1200;
  if (tier > 300) params.set('size', String(tier));
  if (token) params.set('v', token);
  const query = params.toString();
  return `${BASE}/thumbnail/${fileId}${query ? `?${query}` : ''}`;
}

export function imageFileUrl(fileId: number, token?: string): string {
  const query = token ? `?v=${encodeURIComponent(token)}` : '';
  return `${BASE}/image-file/${fileId}${query}`;
}

export const api = {
  getImages: (params: {
    q?: string; sort?: string; order?: string; folder?: string;
    rating?: string; offset?: number; limit?: number;
    blacklist?: string; duplicates_only?: boolean; duplicate_scope?: string; favorites_only?: boolean; collection_id?: number;
  }, signal?: AbortSignal) => get<PaginatedImages>('/images', params as Record<string, string | number | boolean>, signal),

  getRandomImage: (params: {
    q?: string; folder?: string; rating?: string; blacklist?: string;
    duplicates_only?: boolean; duplicate_scope?: string; favorites_only?: boolean; collection_id?: number; collections_only?: boolean;
  }) => get<{ id: number }>('/images/random', params as Record<string, string | number | boolean>),

  getImage: (postId: number, params?: { record_view?: boolean }) =>
    get<ImageDetail>(`/images/${postId}`, params),

  refreshImageRelations: (postId: number) =>
    post<ImageDetail>(`/images/${postId}/relations/refresh`),

  spamHeart: (postId: number) =>
    post<{ heart_spam_count: number }>(`/images/${postId}/heart-spam`),

  moveImageToFolder: (postId: number, folder: string) =>
    put<ImageDetail>(`/images/${postId}/folder`, { folder }),

  moveImagesToFolder: (postIds: number[], folder: string) =>
    put<{ status: string; moved_post_ids: number[]; errors: Record<string, unknown> }>(
      '/images/batch/folder',
      { post_ids: postIds, folder },
    ),

  addUserImageTag: (postId: number, name: string, category: string) =>
    post<{ tags: Record<string, string[]> }>(`/images/${postId}/user-tags`, { name, category }),

  removeUserImageTag: (postId: number, name: string, category: string) =>
    del<{ tags: Record<string, string[]> }>(
      `/images/${postId}/user-tags/${encodeURIComponent(name)}?category=${encodeURIComponent(category)}`
    ),

  openImageLocation: (postId: number) =>
    post<{ status: string; path: string }>(`/images/${postId}/open-location`),

  getHomeTags: (params?: { rating?: string; featured_limit?: number; group_limit?: number }) =>
    get<HomeTags>('/home/tags', params as Record<string, string | number>),

  getHomeImageRails: (params?: { rating?: string; per_rail?: number }) =>
    get<HomeImageRails>('/home/image-rails', params as Record<string, string | number>),

  getDailyChallenge: (params?: { rating?: string }) =>
    get<DailyChallenge>('/challenges/daily', params as Record<string, string>),

  suggestChallengeCharacters: (params: { q: string; rating?: string; limit?: number }) =>
    get<TagInfo[]>('/challenges/characters/suggest', params as Record<string, string | number>),

  getTags: (params?: { category?: string; q?: string; letter?: string; sort?: string; order?: string; offset?: number; limit?: number; min_count?: number; source?: string }, signal?: AbortSignal) =>
    get<PaginatedTags>('/tags', params as Record<string, string | number>, signal),

  getTagWiki: (tagName: string, params?: { refresh?: boolean; category?: string }) =>
    get<TagWikiInfo>(`/tags/${encodeURIComponent(tagName)}/wiki`, params),

  getRandomTag: (params?: { category?: string; min_count?: number }) =>
    get<TagInfo>('/tags/random', params as Record<string, string | number>),

  suggestTags: (q: string, category?: string) => get<TagInfo[]>('/tags/suggest', { q, category }),

  getRelatedTags: (tags: string[], limit = 30) =>
    get<Record<string, TagInfo[]>>('/tags/related', { tags: tags.join(','), limit }),

  getArtistFollows: () =>
    get<ArtistFollowInfo[]>('/artist-follows'),

  getArtistFollowNames: () =>
    get<{ name: string; category: string; added_at: string }[]>('/artist-follows/names'),

  followArtist: (tagName: string, displayName?: string | null) =>
    post<ArtistFollowInfo>(
      `/artist-follows/${encodeURIComponent(tagName)}${displayName ? `?display_name=${encodeURIComponent(displayName)}` : ''}`,
    ),

  unfollowArtist: (tagName: string) =>
    del<{ status: string; name: string }>(`/artist-follows/${encodeURIComponent(tagName)}`),

  checkArtistFollow: (tagName: string, limit = 12, initializeNotifications = false) =>
    post<ArtistFollowCheckResult>(
      `/artist-follows/${encodeURIComponent(tagName)}/check?limit=${limit}&initialize_notifications=${initializeNotifications}`,
    ),

  markArtistFollowSeen: (tagName: string) =>
    post<ArtistFollowInfo>(`/artist-follows/${encodeURIComponent(tagName)}/seen`),

  getArtistProfileAssets: (tagName: string) =>
    get<ArtistProfileAsset[]>(`/artist-profile-assets/${encodeURIComponent(tagName)}`),

  refreshArtistProfileAssets: (tagName: string) =>
    post<ArtistProfileArchiveResult>(`/artist-profile-assets/${encodeURIComponent(tagName)}/refresh`),

  refreshFollowedArtistProfileAssets: () =>
    post<ArtistProfileBulkArchiveResult>('/artist-profile-assets/refresh-followed'),

  getPopularityPeriods: (params?: {
    period?: 'day' | 'month' | 'year';
    q?: string;
    folder?: string;
    rating?: string;
    blacklist?: string;
    limit?: number;
  }) => get<PopularityPeriod[]>('/popularity/periods', params as Record<string, string | number>),

  getTimelapseFrames: (params?: {
    q?: string;
    folder?: string;
    rating?: string;
    blacklist?: string;
    duplicates_only?: boolean;
    duplicate_scope?: string;
    frame_count?: number;
    favorites_only?: boolean;
    collection_id?: number;
  }) => get<TimelapseFrames>('/timelapse/frames', params as Record<string, string | number | boolean>),

  getFolders: () => get<FolderInfo[]>('/folders'),

  registerFolder: (path: string) =>
    post<{ status: string; name: string; selector: string; path: string; root_id: string; sync: string; active_tool_id?: string }>('/folders', { path }),

  browseFolder: () =>
    post<{ path: string | null }>('/folders/browse'),

  rescanFolder: (identifier: string) =>
    post<ToolRunResult>(`/folders/${encodeURIComponent(identifier)}/rescan`),

  relocateFolder: (rootId: string, path: string) =>
    put<FolderRelocateResult>(`/folders/${encodeURIComponent(rootId)}/path`, { path }),

  getFolderRemovalPreview: (name: string) =>
    get<FolderRemovalPreview>(`/folders/${encodeURIComponent(name)}/removal-preview`),

  removeFolder: (name: string, mode: FolderRemovalMode = 'unindex_only') =>
    del<FolderRemovalResult>(`/folders/${encodeURIComponent(name)}`, { mode }),

  getStats: () => get<Stats>('/stats'),

  getUserSetting: (key: string) =>
    get<UserSetting>(`/user-settings/${encodeURIComponent(key)}`),

  putUserSetting: (key: string, value: string) =>
    put<UserSetting>(`/user-settings/${encodeURIComponent(key)}`, { value }),

  toggleFavorite: (fileId: number) =>
    post<{ status: string; added_at: string | null }>(`/favorites/${fileId}`),

  updateFavorites: (fileIds: number[], action: 'add' | 'remove') =>
    put<{ status: string; updated_file_ids: number[]; added_at_by_file: Record<string, string | null> }>(
      '/favorites/batch',
      { file_ids: fileIds, action },
    ),

  toggleFavoritePin: (fileId: number) =>
    post<{ status: string; pinned_at: string | null }>(`/favorites/${fileId}/pin`),

  getFavoriteIds: () => get<number[]>('/favorites/ids'),

  getFavoriteTags: () =>
    get<Record<string, TagInfo[]>>('/favorite-tags'),

  toggleFavoriteTag: (tagName: string, category: string) =>
    post<{ status: string }>(`/favorite-tags/${encodeURIComponent(tagName)}?category=${encodeURIComponent(category)}`),

  toggleFavoriteTagPin: (tagName: string, category: string) =>
    post<{ status: string; pinned_at: string | null }>(`/favorite-tags/${encodeURIComponent(tagName)}/pin?category=${encodeURIComponent(category)}`),

  getFavoriteTagNames: () =>
    get<{ name: string; category: string; pinned_at?: string | null }[]>('/favorite-tags/names'),

  getFavoriteTagCombos: () =>
    get<FavoriteTagCombo[]>('/favorite-tag-combos'),

  createFavoriteTagCombo: (tags: string[], name?: string) =>
    post<FavoriteTagCombo>('/favorite-tag-combos', { tags, name }),

  deleteFavoriteTagCombo: (id: number) =>
    del<{ status: string; id: number }>(`/favorite-tag-combos/${id}`),

  getBlacklistTags: () =>
    get<TagInfo[]>('/blacklist-tags'),

  addBlacklistTag: (tagName: string) =>
    post<{ status: string; name: string }>(`/blacklist-tags/${encodeURIComponent(tagName)}`),

  removeBlacklistTag: (tagName: string) =>
    del<{ status: string; name: string }>(`/blacklist-tags/${encodeURIComponent(tagName)}`),

  getBlacklistTagNames: () =>
    get<string[]>('/blacklist-tags/names'),

  getCollections: () => get<CollectionInfo[]>('/collections'),

  getCollectionMemberships: (fileIds: number[]) =>
    post<{ memberships: Record<string, number[]> }>('/collections/memberships', { file_ids: fileIds }),

  createCollection: (name: string, description = '') =>
    post<CollectionInfo>('/collections', { name, description }),

  updateCollection: (id: number, name: string, description = '') =>
    put<CollectionInfo>(`/collections/${id}`, { name, description }),

  deleteCollection: (id: number) => del<{ status: string }>(`/collections/${id}`),

  toggleCollectionPin: (id: number) =>
    post<{ status: string; pinned_at: string | null }>(`/collections/${id}/pin`),

  toggleCollectionImagePin: (id: number, fileId: number) =>
    post<{ status: string; pinned_at: string | null }>(`/collections/${id}/images/${fileId}/pin`),

  updateCollectionImages: (id: number, fileIds: number[], action: 'add' | 'remove') =>
    put<{ status: string; added_at: string | null; added_at_by_file: Record<string, string | null> }>(
      `/collections/${id}/images`,
      { file_ids: fileIds, action },
    ),

  getTools: () => get<ToolInfo[]>('/tools'),

  getAutomation: () => get<AutomationStatus>('/automation'),

  setAutomation: (enabled: boolean, intervalMinutes?: number) =>
    put<AutomationStatus>('/automation', { enabled, interval_minutes: intervalMinutes ?? null }),

  runTool: (toolId: string) => post<ToolRunResult>(`/tools/${toolId}/run`),

  getToolStatus: (toolId: string) => get<ToolStatus>(`/tools/${toolId}/status`),

  cancelTool: (toolId: string) => post<ToolRunResult>(`/tools/${toolId}/cancel`),

  getToolFolders: () => get<ToolFolder[]>('/tools/folders'),

  runBackfill: (folder?: string, limit?: number) =>
    post<ToolRunResult>('/tools/backfill/run', {
      folder: folder || null,
      limit: limit && limit > 0 ? limit : null,
    }),

  getDanbooruCredentials: () => get<DanbooruCredentialStatus>('/danbooru/credentials'),

  saveDanbooruCredentials: (username: string, apiKey?: string) =>
    put<DanbooruCredentialStatus>('/danbooru/credentials', { username, api_key: apiKey || null }),

  clearDanbooruCredentials: () => del<DanbooruCredentialStatus>('/danbooru/credentials'),

  checkDanbooruCredentials: () =>
    post<{ status: string; username: string; user_id: number | null; source: string }>('/danbooru/credentials/check'),

  getStorageConfiguration: () => get<StorageConfiguration>('/storage'),

  getImportPipeline: () => get<ImportPipelineStatus>('/import-pipeline'),

  getImportTask: (afterIndex?: number) =>
    get<ToolStatus>('/import-pipeline/task', { after_index: afterIndex }),

  runImport: (phase: ImportPhase, folder?: string, limit?: number, confirmNetwork = false) =>
    post<ToolRunResult>('/import-pipeline/run', {
      phase,
      folder: folder || null,
      limit: limit && limit > 0 ? limit : null,
      confirm_network: confirmNetwork,
    }),

  cancelImport: () => post<ToolRunResult>('/import-pipeline/cancel'),

  getBackupConfiguration: () => get<BackupConfiguration>('/backups'),

  getLocalRecovery: () => get<LocalRecoveryStatus>('/local-recovery'),

  createLocalRecoveryCheckpoint: () =>
    post<LocalRecoveryStatus & { status: string; created: boolean; message: string }>('/local-recovery/checkpoint'),

  configureBackups: (components: BackupComponents) =>
    put<BackupConfiguration>('/backups', { components }),

  estimateBackup: (components: BackupComponents) =>
    post<BackupEstimate>('/backups/estimate', { components }),

  createMetadataBackup: (components: BackupComponents) =>
    post<BackupResult>('/backups/create', { components }),

  inspectMetadataBackup: (name: string) =>
    get<BackupManifest>(`/backups/${encodeURIComponent(name)}/inspect`),

  restoreMetadataBackup: (name: string) =>
    post<BackupRestoreResult>('/backups/restore', { name }),

  getThumbnailCache: () => get<ThumbnailCacheStatus>('/thumbnails/cache'),

  cleanupThumbnailCache: () =>
    post<ThumbnailCacheStatus & { removed: number; removed_bytes: number }>('/thumbnails/cache/cleanup'),

  clearThumbnailCache: () =>
    post<ThumbnailCacheStatus & { removed: number }>('/thumbnails/cache/clear'),

  setThumbnailCacheLimit: (limitGb: number) =>
    put<ThumbnailCacheStatus>('/thumbnails/cache/limit', { limit_gb: limitGb }),
};

export interface AutomationStatus {
  enabled: boolean;
  enabled_at: string | null;
  interval_minutes: number;
  last_run_at: string | null;
  candidate_count: number;
}

export interface StorageConfiguration {
  metadata_dir: string;
  documents_default: string;
  suite_home: string;
  module_home: string;
  library_dir: string;
  config_file: string;
  gallery_dl_dir: string;
  log_dir: string;
  runtime_log_file: string;
  access_log_file: string;
  log_retention_files: number;
  mode: 'keivotos' | 'custom';
}

export type ImportPhase = 'discover' | 'enrich' | 'metadata' | 'finalize' | 'all';

export interface ImportPipelineStatus {
  phases: {
    total: number;
    discovered: number;
    enriched: number;
    metadata: number;
    finalized: number;
    errors: number;
    no_match: number;
  };
  task: ToolStatus;
}

export interface BackupComponents {
  user_database: boolean;
  library_database: boolean;
  sidecars: boolean;
  sidecar_history: boolean;
  artist_profile_archive: boolean;
}

export interface BackupEstimateDetail {
  enabled: boolean;
  exists: boolean;
  files: number;
  bytes: number;
  display_size: string;
}

export interface BackupEstimate {
  components: BackupComponents;
  details: Record<keyof BackupComponents, BackupEstimateDetail>;
  total_files: number;
  total_bytes: number;
  display_size: string;
  estimated_compressed_bytes: number;
  estimated_compressed_display: string;
}

export interface BackupListItem {
  name: string;
  path: string;
  bytes: number;
  display_size: string;
  created_at: string;
}

export interface BackupConfiguration {
  destination: string;
  components: BackupComponents;
  estimate: BackupEstimate;
  backups: BackupListItem[];
}

export interface LocalRecoveryStatus {
  enabled: boolean;
  directory: string;
  retention: number;
  count: number;
  latest_name: string | null;
  latest_path: string | null;
  latest_at: string | null;
}

export interface BackupResult {
  status: string;
  path: string;
  name: string;
  bytes: number;
  display_size: string;
  components: BackupComponents;
  message: string;
}

export interface BackupManifest {
  format: string;
  format_version: number;
  created_at: string;
  components: BackupComponents;
  external_images_included: boolean;
  thumbnails_included: boolean;
}

export interface BackupRestoreResult {
  status: string;
  name: string;
  components: BackupComponents;
  rollback_path: string;
  restart_required: boolean;
  message: string;
}

export interface ThumbnailCacheStatus {
  files: number;
  bytes: number;
  legacy_files: number;
  tiers: Record<string, number>;
  limit_bytes: number;
}

export interface ToolInfo {
  id: string;
  name: string;
  description: string;
  command: string;
  status: string;
  output?: string;
  progress?: number;
  total?: number;
  stage?: string | null;
  stage_index?: number;
  stage_total?: number;
  cancellable?: boolean;
  current_file?: string | null;
  current_file_path?: string | null;
  current_file_status?: string | null;
  file_results?: ToolFileResult[];
  result_counts?: Record<string, number>;
  requires_form?: boolean;
  advanced?: boolean;
}

export interface ToolStatus {
  status: string;
  output: string;
  progress?: number;
  total?: number;
  stage?: string | null;
  stage_index?: number;
  stage_total?: number;
  cancellable?: boolean;
  current_file?: string | null;
  current_file_path?: string | null;
  current_file_status?: string | null;
  file_results?: ToolFileResult[];
  result_counts?: Record<string, number>;
}

export interface ToolFileResult {
  filename: string;
  path: string;
  status: 'matched' | 'no_match' | 'error';
  detail: string;
  index?: number;
  total?: number;
}

export interface ToolRunResult {
  status: string;
  active_tool_id?: string;
}

export interface ToolFolder {
  name: string;
  path: string;
  registered: boolean;
  exists: boolean;
}

export interface DanbooruCredentialStatus {
  username: string | null;
  has_api_key: boolean;
  has_saved_api_key: boolean;
  has_saved_credentials: boolean;
  configured: boolean;
  source: 'none' | 'saved' | 'environment';
}

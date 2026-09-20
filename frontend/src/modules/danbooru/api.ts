import { BASE, get, post, put, del } from '../../lib/http';
import type { ImageSummary, PaginatedImages, TagInfo, TagWikiTextPart, TagWikiTextLine, TagWikiExample, TagWikiSection, ArtistUrl, TagWikiInfo, ArtistFollowInfo, ArtistFollowCheckResult, ArtistProfileAsset, ArtistProfileArchiveResult, ArtistProfileBulkArchiveResult, HomeCoverCandidate, HomeTagInfo, HomeTags, HomeImageRailItem, HomeImageRail, HomeImageRails, DailyChallengeImage, DailyChallengeOption, DailyChallengeClues, DailyChallenge, FavoriteTagCombo, PaginatedTags, PopularityPeriod, TimelapseFrames, RelatedImageInfo, ImageRelations, ImageDetail, FolderInfo, FolderRelocateResult, FolderRemovalMode, FolderRemovalPreview, FolderRemovalResult, CollectionPreviewItem, CollectionInfo, Stats, AutomationStatus, ImportPhase, ImportPipelineStatus, ToolInfo, ToolStatus, ToolFileResult, ToolRunResult, ToolFolder, DanbooruCredentialStatus } from './apiTypes';
const THUMBNAIL_VERSION = 'v4';
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

export const danbooruApi = {
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

getImportPipeline: () => get<ImportPipelineStatus>('/import-pipeline'),

getImportTask: (afterIndex?: number) =>
    get<ToolStatus>('/import-pipeline/task', { after_index: afterIndex }),

runImport: (phase: ImportPhase, folder?: string, limit?: number, confirmNetwork = false, fetchMetadata = false) =>
    post<ToolRunResult>('/import-pipeline/run', {
      phase,
      folder: folder || null,
      limit: limit && limit > 0 ? limit : null,
      confirm_network: confirmNetwork,
      fetch_metadata: fetchMetadata,
    }),

cancelImport: () => post<ToolRunResult>('/import-pipeline/cancel'),
};

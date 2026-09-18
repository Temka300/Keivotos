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

export interface AutomationStatus {
  enabled: boolean;
  enabled_at: string | null;
  interval_minutes: number;
  last_run_at: string | null;
  candidate_count: number;
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

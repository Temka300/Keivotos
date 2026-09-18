// Compatibility client; method references are owned by the clients below.
import { suiteDataApi } from './suiteDataApi';
import { danbooruApi } from '../modules/danbooru/api';
export { thumbnailUrl, imageFileUrl } from '../modules/danbooru/api';
export type { ImageSummary, PaginatedImages, TagInfo, TagWikiTextPart, TagWikiTextLine, TagWikiExample, TagWikiSection, ArtistUrl, TagWikiInfo, ArtistFollowInfo, ArtistFollowCheckResult, ArtistProfileAsset, ArtistProfileArchiveResult, ArtistProfileBulkArchiveResult, HomeCoverCandidate, HomeTagInfo, HomeTags, HomeImageRailItem, HomeImageRail, HomeImageRails, DailyChallengeImage, DailyChallengeOption, DailyChallengeClues, DailyChallenge, FavoriteTagCombo, PaginatedTags, PopularityPeriod, TimelapseFrames, RelatedImageInfo, ImageRelations, ImageDetail, FolderInfo, FolderRelocateResult, FolderRemovalMode, FolderRemovalPreview, FolderRemovalResult, UserSetting, CollectionPreviewItem, CollectionInfo, Stats, AutomationStatus, StorageConfiguration, ImportPhase, ImportPipelineStatus, BackupComponents, BackupEstimateDetail, BackupEstimate, BackupListItem, BackupConfiguration, LocalRecoveryStatus, BackupResult, BackupManifest, BackupRestoreResult, ThumbnailCacheStatus, ToolInfo, ToolStatus, ToolFileResult, ToolRunResult, ToolFolder, DanbooruCredentialStatus } from './apiTypes';
export const api = {
  ...danbooruApi,
  getUserSetting: suiteDataApi.getUserSetting,
  putUserSetting: suiteDataApi.putUserSetting,
  getStorageConfiguration: suiteDataApi.getStorageConfiguration,
  getBackupConfiguration: suiteDataApi.getBackupConfiguration,
  getLocalRecovery: suiteDataApi.getLocalRecovery,
  createLocalRecoveryCheckpoint: suiteDataApi.createLocalRecoveryCheckpoint,
  configureBackups: suiteDataApi.configureBackups,
  estimateBackup: suiteDataApi.estimateBackup,
  createMetadataBackup: suiteDataApi.createMetadataBackup,
  inspectMetadataBackup: suiteDataApi.inspectMetadataBackup,
  restoreMetadataBackup: suiteDataApi.restoreMetadataBackup,
  getThumbnailCache: suiteDataApi.getThumbnailCache,
  cleanupThumbnailCache: suiteDataApi.cleanupThumbnailCache,
  clearThumbnailCache: suiteDataApi.clearThumbnailCache,
  setThumbnailCacheLimit: suiteDataApi.setThumbnailCacheLimit,
};

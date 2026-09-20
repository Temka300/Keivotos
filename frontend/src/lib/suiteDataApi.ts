import { get, post, put } from './http';
import type { DiagnosticsPreferences, UserSetting, StorageConfiguration, BackupComponents, BackupEstimateDetail, BackupEstimate, BackupListItem, BackupConfiguration, LocalRecoveryStatus, BackupResult, BackupManifest, BackupRestoreResult, ThumbnailCacheStatus } from './suiteApiTypes';

export const suiteDataApi = {
getDiagnostics: () => get<DiagnosticsPreferences>('/diagnostics'),
configureDiagnostics: (preferences: DiagnosticsPreferences) => put<DiagnosticsPreferences>('/diagnostics', preferences),
openDiagnostics: (target: 'data' | 'logs' | 'runtime' | 'access') => post<{ status: string }>(`/diagnostics/open/${target}`),
getUserSetting: (key: string) =>
    get<UserSetting>(`/user-settings/${encodeURIComponent(key)}`),

putUserSetting: (key: string, value: string) =>
    put<UserSetting>(`/user-settings/${encodeURIComponent(key)}`, { value }),

getStorageConfiguration: () => get<StorageConfiguration>('/storage'),

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

export interface UserSetting {
  key: string;
  value: string;
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

export type BackupComponents = Record<string, boolean>;

export interface BackupEstimateDetail {
  owner: string;
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
  preserved_count?: number;
  preserved_directory?: string;
}

export interface BackupResult {
  omitted_components?: string[];
  status: string;
  path: string;
  name: string;
  bytes: number;
  display_size: string;
  components: BackupComponents;
  message: string;
}

export interface BackupManifest {
  component_owners?: Record<string, string>;
  omitted_components?: string[];
  format: string;
  format_version: number;
  created_at: string;
  components: BackupComponents;
  external_images_included: boolean;
  thumbnails_included: boolean;
}

export interface BackupRestoreResult {
  attachments?: { restored: number; existing: number; missing: number; failed: number };
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

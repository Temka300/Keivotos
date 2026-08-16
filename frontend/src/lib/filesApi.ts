// Files base API client (V1.1.0).
//
// Deliberately isolated from the Danbooru `api.ts` client, mirroring the
// backend's `files_base` isolation. Talks only to `/api/files/*`.

const BASE = '/api/files';

export interface FileNode {
  source_id: string;
  relative_path: string;
  parent: string;
  name: string;
  ext: string | null;
  is_dir: boolean;
  size: number | null;
  mtime: number | null;
  available: boolean;
}

export interface SourceInfo {
  source_id: string;
  path: string;
  display_name: string;
  role: string;
  visible: boolean;
  added_at: string | null;
}

export interface ScanSummary {
  added: number;
  updated: number;
  files: number;
  directories: number;
  unavailable: number;
}

export interface HashProgress {
  hashed: number;
  failed: number;
  remaining: number;
}

export interface DuplicateGroup {
  content_hash: string;
  files: FileNode[];
}

export interface FsEntry {
  name: string;
  path: string;
}

export interface FsListing {
  path: string;
  parent: string | null;
  is_root: boolean;
  entries: FsEntry[];
}

export interface PickResult {
  path: string | null;
  native: boolean;
}

export interface AttachmentStore {
  path: string;
  /** 'managed' = hidden with the suite data; 'folder' = visible in the chosen folder. */
  mode: 'managed' | 'folder';
  is_default: boolean;
  default: string;
}

export type LinkKind = 'source' | 'discussion' | 'mirror' | 'author' | 'other';

export interface AnnotationLink {
  url: string;
  label: string;
  kind: string;
}

export interface AnnotationAttachment {
  id: number;
  content_hash: string;
  file_name: string;
  media_type: string;
  size: number;
  width: number | null;
  height: number | null;
  caption: string;
  is_cover: boolean;
  position: number;
}

export interface Annotation {
  id: number;
  subject_kind: string;
  content_hash: string | null;
  source_id: string;
  relative_path: string;
  description: string;
  author: string;
  extra_info: string;
  created_at: string | null;
  updated_at: string | null;
  links: AnnotationLink[];
  attachments: AnnotationAttachment[];
}

export interface AnnotationRequest {
  source_id: string;
  path: string;
  description: string;
  author: string;
  extra_info: string;
  links: AnnotationLink[];
}

export interface ArchiveEntry {
  name: string;
  size: number;
  compressed_size: number;
  is_dir: boolean;
}

export interface ArchiveListing {
  entries: ArchiveEntry[];
  total_entries: number;
  truncated: boolean;
  total_size: number;
  compressed_size: number;
}

/** An API failure that still knows its HTTP status, so callers can branch. */
export interface ApiError extends Error {
  status: number;
}

async function apiError(res: Response): Promise<ApiError> {
  let detail = '';
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') detail = data.detail;
    else if (data?.detail) detail = JSON.stringify(data.detail);
  } catch {
    // Non-JSON error body; fall back to the status line.
  }
  const error = new Error(detail || `API ${res.status}: ${res.statusText}`) as ApiError;
  error.status = res.status;
  return error;
}

async function getJson<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

export const filesApi = {
  listSources: () => getJson<SourceInfo[]>('/sources'),
  scanSource: (sourceId: string) =>
    send<ScanSummary>('POST', `/sources/${encodeURIComponent(sourceId)}/scan`),
  browse: (sourceId: string, parent = '') =>
    getJson<FileNode[]>('/browse', { source_id: sourceId, parent }),
  search: (q: string, sourceId?: string) =>
    getJson<FileNode[]>('/search', { q, source_id: sourceId }),
  computeHashes: (limit = 2000) => send<HashProgress>('POST', `/hash?limit=${limit}`),
  listDuplicates: () => getJson<DuplicateGroup[]>('/duplicates'),
  browseFs: (path = '') => getJson<FsListing>('/fs', { path }),
  pickFolder: () => send<PickResult>('POST', '/pick'),
  // Where origin-note attachment images/videos are stored. Setting null resets
  // to the default (the Files base home).
  getAttachmentStore: () => getJson<AttachmentStore>('/attachment-store'),
  setAttachmentStore: (path: string | null) =>
    send<AttachmentStore>('PUT', '/attachment-store', { path }),
  // URL for streaming a file's bytes (preview/open). The backend resolves it
  // against the source root and refuses anything outside it.
  fileUrl: (sourceId: string, relativePath: string) => {
    const url = new URL(BASE + '/file', window.location.origin);
    url.searchParams.set('source_id', sourceId);
    url.searchParams.set('path', relativePath);
    return url.toString();
  },
  // URL for a cached WebP thumbnail of one file. The response is immutable, so
  // ``version`` (mtime/size) is what makes a replaced file show its new image
  // instead of the browser's cached one; the server ignores the value.
  thumbnailUrl: (sourceId: string, relativePath: string, size: number, version: string) => {
    const url = new URL(BASE + '/thumbnail', window.location.origin);
    url.searchParams.set('source_id', sourceId);
    url.searchParams.set('path', relativePath);
    url.searchParams.set('size', String(size));
    url.searchParams.set('v', version);
    return url.toString();
  },
  // Read-only table of contents for an archive. The server parses the central
  // directory only — nothing is extracted or decompressed.
  listArchive: (sourceId: string, path: string) =>
    getJson<ArchiveListing>('/archive', { source_id: sourceId, path }),
  listAnnotated: (sourceId: string) =>
    getJson<string[]>('/annotated', { source_id: sourceId }),
  getInfo: (sourceId: string, path: string) =>
    getJson<Annotation | null>('/info', { source_id: sourceId, path }),
  saveInfo: (request: AnnotationRequest) =>
    send<Annotation | null>('PUT', '/info', request),
  // Carry another subject's origin note onto this one. Additive: links and
  // attachments merge, and the server refuses with 409 rather than replacing an
  // existing description unless `overwrite` is set.
  copyInfo: (
    fromSourceId: string,
    fromPath: string,
    toSourceId: string,
    toPath: string,
    overwrite = false,
  ) =>
    send<Annotation>('POST', '/info/copy', {
      source: { source_id: fromSourceId, path: fromPath },
      target: { source_id: toSourceId, path: toPath },
      overwrite_description: overwrite,
    }),
  deleteInfo: (sourceId: string, path: string) =>
    send<{ deleted: boolean }>(
      'DELETE',
      `/info?source_id=${encodeURIComponent(sourceId)}&path=${encodeURIComponent(path)}`,
    ),
  attachmentUrl: (attachmentId: number) => `${BASE}/attachment/${attachmentId}`,
  uploadAttachment: async (sourceId: string, path: string, file: File): Promise<Annotation> => {
    const params = new URLSearchParams({
      source_id: sourceId,
      path,
      file_name: file.name,
    });
    const res = await fetch(`${BASE}/attachment?${params.toString()}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
    if (!res.ok) throw await apiError(res);
    return res.json();
  },
  deleteAttachment: (attachmentId: number) =>
    send<{ deleted: boolean }>('DELETE', `/attachment/${attachmentId}`),
  openFile: (sourceId: string, path: string) =>
    send<{ status: string }>('POST', '/open', { source_id: sourceId, path }),
  revealFile: (sourceId: string, path: string) =>
    send<{ status: string }>('POST', '/reveal', { source_id: sourceId, path }),
};

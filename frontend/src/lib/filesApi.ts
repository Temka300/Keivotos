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
  registerSource: (path: string, display_name?: string) =>
    send<SourceInfo>('POST', '/sources', { path, display_name }),
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
};

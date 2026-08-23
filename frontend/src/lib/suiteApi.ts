// Suite module registry client (V1.1.0). Isolated, like filesApi.ts.

const BASE = '/api/suite';

export interface SuiteModule {
  id: string;
  slug: string;
  name: string;
  enabled: boolean;
  disableable: boolean;
  is_base: boolean;
  api_prefix: string;
}

export interface FolderChange {
  source_id: string | null;
  path: string;
  display_name: string;
  role: string;
  visible: boolean;
  forget: boolean;
}

export interface ManagedFolder extends FolderChange {
  source_id: string;
  added_at: string | null;
}

export interface FolderBatchResult {
  sources: ManagedFolder[];
  adopted: string[];
  released: string[];
  forgotten: string[];
  operations: Record<string, unknown>[];
}

export interface FolderForgetPreview {
  source_id: string;
  display_name: string;
  base_files: number;
  module_files: number;
  sidecars_preserved: number;
}

export interface FolderRescanResult {
  source_id: string;
  /** Base filesystem index counts (added/updated/…). */
  base: Record<string, number>;
  /** Owning module's rescan result — e.g. {status, active_tool_id} for Danbooru. */
  module: Record<string, unknown>;
}

export interface FolderRelocateResult {
  source_id: string;
  files_updated: number;
}

/** The folder's own name, used as the default label for a newly added source. */
export function displayNameForPath(path: string): string {
  const parts = path.replace(/[\\/]+$/, '').split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/** Compare two paths the way the backend does: separator- and case-insensitive. */
export function normalizedPath(path: string): string {
  return path.replace(/[\\/]+/g, '/').replace(/\/+$/, '').toLocaleLowerCase();
}

async function apiError(res: Response): Promise<Error> {
  let detail = '';
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') detail = data.detail;
  } catch {
    // Non-JSON error body; fall back to the status line.
  }
  return new Error(detail || `API ${res.status}: ${res.statusText}`);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path);
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: 'POST' });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

export const suiteApi = {
  listModules: () => getJson<SuiteModule[]>('/modules'),
  enableModule: (id: string) => post<SuiteModule>(`/modules/${encodeURIComponent(id)}/enable`),
  disableModule: (id: string) => post<SuiteModule>(`/modules/${encodeURIComponent(id)}/disable`),
  applyFolderChanges: (folders: FolderChange[]) =>
    postJson<FolderBatchResult>('/folders/apply', { folders }),
  previewFolderForget: (sourceId: string) =>
    getJson<FolderForgetPreview>(`/folders/${encodeURIComponent(sourceId)}/forget-preview`),
  rescanFolder: (sourceId: string) =>
    post<FolderRescanResult>(`/folders/${encodeURIComponent(sourceId)}/rescan`),
  relocateFolder: (sourceId: string, path: string) =>
    putJson<FolderRelocateResult>(`/folders/${encodeURIComponent(sourceId)}/path`, { path }),
};

// Existing /api JSON transport; preserve request and error semantics.
export const BASE = '/api';

export async function get<T>(
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

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = 'ApiError'; }
}

export function settingsError(error: unknown, feature: string): string {
  if (error instanceof ApiError && error.status === 404) {
    return `${feature} is unavailable in the running app. Close older Keivotos instances and restart the current build, then retry.`;
  }
  return `${feature}: ${error instanceof Error ? error.message : 'Could not connect. Please retry.'}`;
}

export async function apiError(res: Response): Promise<Error> {
  let detail = '';
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') detail = data.detail;
    else if (data?.detail) detail = JSON.stringify(data.detail);
  } catch {
    // Non-JSON error body; fall back to the status line.
  }
  return new ApiError(res.status, detail || `API ${res.status}: ${res.statusText}`);
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

export async function put<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await apiError(res);
  return res.json();
}

export async function del<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
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

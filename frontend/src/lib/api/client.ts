import { env } from '$env/dynamic/public';
import { auth, type Profile } from '$lib/auth.svelte';

const base = env.PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export class FriendlyError extends Error { constructor(message: string, public status: number) { super(message); } }

async function refreshAccess(): Promise<boolean> {
  if (!auth.refreshToken) return false;
  const response = await fetch(`${base}/auth/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: auth.refreshToken }) });
  if (!response.ok) { auth.clear(); return false; }
  const tokens = await response.json(); auth.save(tokens.access_token, tokens.refresh_token); return true;
}

export async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (auth.accessToken) headers.set('Authorization', `Bearer ${auth.accessToken}`);
  let response: Response;
  try { response = await fetch(`${base}${path}`, { ...options, headers }); }
  catch { throw new FriendlyError('Connection lost. Check your network and try again.', 0); }
  if (response.status === 401 && retry && await refreshAccess()) return api<T>(path, options, false);
  if (response.status === 429 && retry && (options.method ?? 'GET') === 'GET') {
    const retrySeconds = Math.min(Number(response.headers.get('Retry-After') || '2'), 5);
    await new Promise((resolve) => setTimeout(resolve, retrySeconds * 1000));
    return api<T>(path, options, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const friendly = response.status === 409 ? (body.detail || 'This report has changed. Refresh and try again.') : body.detail;
    throw new FriendlyError(friendly || 'Something went wrong. Please try again.', response.status);
  }
  return response.status === 204 ? undefined as T : response.json();
}

export { base };

/** Build a query string, leaving out empty values. */
export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== '' && value !== null && value !== undefined && value !== false) search.set(key, String(value));
  const text = search.toString();
  return text ? `?${text}` : '';
}

/** Fetch an authenticated file and hand it to the browser as a download. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const send = () => fetch(`${base}${path}`, { headers: auth.accessToken ? { Authorization: `Bearer ${auth.accessToken}` } : {} });
  let response: Response;
  try { response = await send(); if (response.status === 401 && await refreshAccess()) response = await send(); }
  catch { throw new FriendlyError('Connection lost. Check your network and try again.', 0); }
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new FriendlyError(body.detail || 'The download could not be prepared.', response.status); }
  const name = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function loadProfile(): Promise<Profile> {
  const me = await api<Profile>('/auth/me');
  auth.setProfile(me);
  return me;
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

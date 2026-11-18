import { browser } from '$app/environment';
import type { Permission, Role } from '$lib/types';

export interface Profile {
  id: number; // the staff profile id, which is what reports reference as assigned_officer.id
  account_id: number | null;
  name: string;
  email: string;
  role: Role;
  role_label: string;
  permissions: Permission[];
  global_scope: boolean;
  offices: string[];
  office_ids: number[];
}

function read<T>(key: string): T | null {
  if (!browser) return null;
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) as T : null; } catch { return null; }
}
function write(key: string, value: unknown) {
  if (!browser) return;
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value)); } catch { /* storage unavailable */ }
}

// Offline snapshots of reports. Personal data, so they go with the session.
const CACHE_PREFIXES = ['cached_reports_', 'report:'];

class AuthState {
  accessToken = $state(browser ? localStorage.getItem('access_token') : null);
  refreshToken = $state(browser ? localStorage.getItem('refresh_token') : null);
  profile = $state<Profile | null>(read<Profile>('profile'));

  get name() { return this.profile?.name ?? null; }
  get office() { return this.profile?.offices.join(', ') || null; }
  get roleLabel() { return this.profile?.role_label ?? 'Officer'; }

  can(permission: Permission) { return this.profile?.permissions.includes(permission) ?? false; }
  canAny(...permissions: Permission[]) { return permissions.some((item) => this.can(item)); }

  save(access: string, refresh: string) {
    this.accessToken = access; this.refreshToken = refresh;
    write('access_token', access); write('refresh_token', refresh);
  }
  setProfile(profile: Profile) { this.profile = profile; write('profile', profile); }
  clear() {
    this.accessToken = null; this.refreshToken = null; this.profile = null;
    if (!browser) return;
    for (const key of ['access_token', 'refresh_token', 'profile', 'officer_name', 'officer_office']) write(key, null);
    try {
      for (const key of Object.keys(localStorage)) if (CACHE_PREFIXES.some((prefix) => key.startsWith(prefix))) localStorage.removeItem(key);
    } catch { /* storage unavailable */ }
    if ('caches' in window) caches.keys().then((keys) => keys.forEach((key) => caches.delete(key))).catch(() => {});
  }
}
export const auth = new AuthState();

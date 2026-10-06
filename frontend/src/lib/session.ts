import { goto } from '$app/navigation';
import { api } from '$lib/api/client';
import { auth } from '$lib/auth.svelte';
import { connection } from '$lib/realtime.svelte';

/** Revoke the refresh token server-side, then forget everything on this device. */
export function signOut() {
  const refresh = auth.refreshToken;
  if (refresh) api('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: refresh }) }).catch(() => {});
  auth.clear();
  connection.close();
  goto('/login');
}

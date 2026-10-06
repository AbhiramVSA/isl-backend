import { browser } from '$app/environment';
import { auth } from '$lib/auth.svelte';
import { base } from '$lib/api/client';

class ConnectionState {
  connected = $state(false);
  /** True once a connection attempt has failed or dropped; false while first connecting. */
  lost = $state(false);
  lastEvent = $state<Record<string, unknown> | null>(null);
  private socket: WebSocket | null = null;
  private retry = 1000;
  connect() {
    if (!browser || !auth.accessToken || this.socket) return;
    const url = new URL(base.replace(/^http/, 'ws') + '/ws/officer');
    url.searchParams.set('access_token', auth.accessToken);
    this.socket = new WebSocket(url);
    this.socket.onopen = () => { this.connected = true; this.lost = false; this.retry = 1000; };
    this.socket.onmessage = (message) => { this.lastEvent = JSON.parse(message.data); };
    this.socket.onclose = () => { this.connected = false; this.socket = null; if (!auth.accessToken) return; this.lost = true; setTimeout(() => this.connect(), this.retry); this.retry = Math.min(this.retry * 2, 30000); };
  }
  close() { const socket = this.socket; this.socket = null; this.lost = false; socket?.close(); }
}
export const connection = new ConnectionState();


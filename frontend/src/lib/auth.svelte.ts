import { browser } from '$app/environment';

class AuthState {
  accessToken = $state(browser ? localStorage.getItem('access_token') : null);
  refreshToken = $state(browser ? localStorage.getItem('refresh_token') : null);
  name = $state(browser ? localStorage.getItem('officer_name') : null);
  office = $state(browser ? localStorage.getItem('officer_office') : null);

  save(access: string, refresh: string) {
    this.accessToken = access; this.refreshToken = refresh;
    if (browser) { localStorage.setItem('access_token', access); localStorage.setItem('refresh_token', refresh); }
  }
  clear() {
    this.accessToken = null; this.refreshToken = null; this.name = null; this.office = null;
    if (browser) { localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); localStorage.removeItem('officer_name'); localStorage.removeItem('officer_office'); }
  }
}
export const auth = new AuthState();

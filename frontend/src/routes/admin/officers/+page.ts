import { redirect } from '@sveltejs/kit';

// Officers became part of Staff & roles.
export function load() { redirect(308, '/admin/staff'); }

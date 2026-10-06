import type { Permission } from '$lib/types';

export const permissionGroups: { label: string; items: { key: Permission; label: string }[] }[] = [
  { label: 'Reports', items: [
    { key: 'reports.view', label: 'View reports' },
    { key: 'reports.respond', label: 'Take and respond to reports' },
    { key: 'reports.assign', label: 'Assign reports to officers' },
    { key: 'reports.prioritize', label: 'Change priority' },
    { key: 'reports.override', label: 'Override status (cancel, reopen)' },
    { key: 'reports.export', label: 'Export to CSV' }
  ] },
  { label: 'People & offices', items: [
    { key: 'staff.view', label: 'View staff' },
    { key: 'staff.manage', label: 'Create and manage staff' },
    { key: 'offices.edit', label: 'Edit office details' },
    { key: 'offices.manage', label: 'Create and deactivate offices' },
    { key: 'reporters.view', label: 'View reporters' },
    { key: 'reporters.manage', label: 'Block reporters' }
  ] },
  { label: 'Oversight', items: [
    { key: 'analytics.view', label: 'Analytics' },
    { key: 'audit.view', label: 'Audit log' }
  ] }
];

/** Generate a strong temporary password (meets the 10-character minimum with room to spare). */
export function temporaryPassword(): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const bytes = crypto.getRandomValues(new Uint8Array(14));
  const body = Array.from(bytes, (byte) => alphabet[byte % alphabet.length]).join('');
  return `${body.slice(0, 7)}-${body.slice(7)}!`;
}

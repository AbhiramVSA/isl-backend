export function parseApiTime(value: string): Date {
  // SQLite can omit the UTC offset when returning timezone-aware columns.
  // API timestamps are UTC, so add Z only when no offset is present.
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  return new Date(hasTimezone ? value : `${value}Z`);
}

export function localDate(value: string): string {
  return parseApiTime(value).toLocaleDateString();
}

export function localDateTime(value: string): string {
  return parseApiTime(value).toLocaleString();
}

export function localTime(value: string): string {
  return parseApiTime(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function relativeTime(value: string): string {
  const date = parseApiTime(value);
  if (Number.isNaN(date.getTime())) return 'Time unavailable';
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 10) return 'just now';
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.floor(seconds / 60); if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.floor(minutes / 60); if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  return date.toLocaleDateString();
}

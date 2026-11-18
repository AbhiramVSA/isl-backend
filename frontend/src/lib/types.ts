export type Priority = 'CRITICAL' | 'HIGH' | 'NORMAL';
export type ReportStatus = 'NEW' | 'ACKNOWLEDGED' | 'ASSIGNED' | 'RESPONDING' | 'ARRIVED' | 'RESOLVED' | 'CANCELLED';

export interface Office { id: number; name: string; address: string; latitude: number; longitude: number; service_radius: number }
export interface Officer { id: number; name: string; badge_number: string; rank: string | null }
export interface Report {
  public_id: string; category: string; description: string; priority: Priority; status: ReportStatus;
  initial_latitude: number; initial_longitude: number; location_accuracy: number | null;
  created_at: string; updated_at: string; acknowledged_at: string | null; responding_at: string | null;
  arrived_at: string | null; resolved_at: string | null; office: Office; assigned_officer: Officer | null;
  transcript_available: boolean;
  reference_code?: string | null; title?: string | null; severity?: string | null; situation_analysis?: string | null;
  recommended_actions?: string[] | null; transcript?: string | null; labels?: string[] | null; duration_ms?: number | null;
  location_label?: string | null; reporter_name?: string | null; source?: string | null;
}
export interface LiveStream {
  stream_id: string; started_at: string; ended_at: string | null; live: boolean; duration_ms: number; frames: number;
  reporter_name: string | null; caption: string; transcript: string; safety: string; report_id: string | null; recording_ready: boolean;
}
export interface ReportsPage { items: Report[]; page: number; page_size: number; total: number }
export interface Location { latitude: number; longitude: number; accuracy: number | null; speed: number | null; heading: number | null; recorded_at: string }
export interface History { event: string; old_status: string | null; new_status: string | null; event_metadata: Record<string, unknown>; created_at: string }
export interface Related { nearby: (Report & { distance_km: number })[]; same_user: Report[]; same_office: Report[] }

export const statusLabel: Record<ReportStatus, string> = {
  NEW: 'New Report', ACKNOWLEDGED: 'Acknowledged', ASSIGNED: 'Assigned', RESPONDING: 'Responding',
  ARRIVED: 'Arrived', RESOLVED: 'Resolved', CANCELLED: 'Cancelled'
};


export type Role = 'USER' | 'OFFICER' | 'DISPATCHER' | 'OFFICE_ADMIN' | 'AUDITOR' | 'ADMIN';
export type AccountStatus = 'ACTIVE' | 'DISABLED';
export type Permission =
  | 'reports.view' | 'reports.respond' | 'reports.assign' | 'reports.prioritize' | 'reports.override' | 'reports.export'
  | 'staff.view' | 'staff.manage' | 'offices.view' | 'offices.manage' | 'offices.edit'
  | 'reporters.view' | 'reporters.manage' | 'audit.view' | 'analytics.view';

export interface Page<T> { items: T[]; page: number; page_size: number; total: number }
export interface OfficeRef { id: number; name: string }
export interface RoleInfo { role: Role; label: string; description: string; permissions: Permission[]; global_scope: boolean; grantable: boolean }
export interface Staff {
  id: number; account_id: number; name: string; email: string; phone: string | null; badge_number: string; rank: string | null;
  role: Role; role_label: string; status: AccountStatus; offices: OfficeRef[]; open_reports: number; created_at: string; last_login_at: string | null;
}
export interface AdminOffice extends Office { active: boolean; created_at: string; staff_count: number; open_reports: number; total_reports: number }
export interface Reporter { id: number; account_id: number; name: string; email: string; phone: string | null; status: AccountStatus; created_at: string; last_login_at: string | null; total_reports: number; open_reports: number }
export type AdminReport = Report;
export interface AuditEntry { id: number; created_at: string; action: string; actor_type: string; actor_id: number | null; actor_name: string | null; actor_email: string | null; target_type: string; target_id: string | null; ip_address: string | null; metadata: Record<string, unknown> }
export interface CountItem { key: string; label: string; count: number }
export interface OfficerLoad { officer_id: number; name: string; active: number; resolved: number }
export interface Analytics {
  days: number; total: number; open: number; resolved: number; critical_open: number; unassigned_open: number;
  avg_acknowledge_minutes: number | null; avg_arrival_minutes: number | null; avg_resolution_minutes: number | null;
  by_status: CountItem[]; by_priority: CountItem[]; by_category: CountItem[];
  daily: { date: string; created: number; resolved: number }[];
  offices: { office_id: number; name: string; total: number; open: number; resolved: number; avg_acknowledge_minutes: number | null }[];
  officers: OfficerLoad[];
}

export const roleLabel: Record<Role, string> = {
  USER: 'Reporter', OFFICER: 'Officer', DISPATCHER: 'Dispatcher', OFFICE_ADMIN: 'Office Admin', AUDITOR: 'Auditor', ADMIN: 'Super Admin'
};
export const priorityLabel: Record<Priority, string> = { CRITICAL: 'Critical', HIGH: 'High', NORMAL: 'Normal' };

export function minutesLabel(value: number | null): string {
  if (value === null) return '—';
  if (value < 1) return '<1 min';
  if (value < 90) return `${Math.round(value)} min`;
  if (value < 60 * 48) return `${(value / 60).toFixed(1)} h`;
  return `${(value / 1440).toFixed(1)} d`;
}

/** "MedicalEmergency" (an Equal app category) → "Medical emergency"; free-text categories pass through. */
export function categoryLabel(category: string): string {
  if (!/^[A-Z][a-z]+(?:[A-Z][a-z]+)+$/.test(category)) return category;
  const words = category.replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

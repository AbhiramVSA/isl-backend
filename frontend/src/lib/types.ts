export type Priority = 'CRITICAL' | 'HIGH' | 'NORMAL';
export type ReportStatus = 'NEW' | 'ACKNOWLEDGED' | 'ASSIGNED' | 'RESPONDING' | 'ARRIVED' | 'RESOLVED' | 'CANCELLED';

export interface Office { id: number; name: string; address: string; latitude: number; longitude: number; service_radius: number }
export interface Officer { id: number; name: string; badge_number: string; rank: string | null }
export interface Report {
  public_id: string; category: string; description: string; priority: Priority; status: ReportStatus;
  initial_latitude: number; initial_longitude: number; location_accuracy: number | null;
  created_at: string; updated_at: string; acknowledged_at: string | null; responding_at: string | null;
  arrived_at: string | null; resolved_at: string | null; office: Office; assigned_officer: Officer | null;
}
export interface ReportsPage { items: Report[]; page: number; page_size: number; total: number }
export interface Location { latitude: number; longitude: number; accuracy: number | null; speed: number | null; heading: number | null; recorded_at: string }
export interface History { event: string; old_status: string | null; new_status: string | null; event_metadata: Record<string, unknown>; created_at: string }
export interface Related { nearby: (Report & { distance_km: number })[]; same_user: Report[]; same_office: Report[] }

export const statusLabel: Record<ReportStatus, string> = {
  NEW: 'New Report', ACKNOWLEDGED: 'Acknowledged', ASSIGNED: 'Assigned', RESPONDING: 'Responding',
  ARRIVED: 'Arrived', RESOLVED: 'Resolved', CANCELLED: 'Cancelled'
};


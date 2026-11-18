import type { AnalyzeJob, Health, ModelCards } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`${url} responded ${res.status}`);
  return (await res.json()) as T;
}

export const fetchHealth = (): Promise<Health> => getJson<Health>("/api/health");
export const fetchModels = (): Promise<ModelCards> => getJson<ModelCards>("/api/models");
export const fetchJob = (jobId: string): Promise<AnalyzeJob> =>
  getJson<AnalyzeJob>(`/api/analyze/${encodeURIComponent(jobId)}`);

export async function submitVideo(file: File): Promise<string> {
  const body = new FormData();
  body.append("file", file, file.name);
  const res = await fetch("/api/analyze", { method: "POST", body });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const j = (await res.json()) as { detail?: unknown; error?: unknown };
      const d = j.detail ?? j.error;
      if (typeof d === "string") detail = d;
    } catch {
      /* body was not JSON */
    }
    throw new Error(`Upload rejected: ${detail}`);
  }
  const j = (await res.json()) as { job_id: string };
  return j.job_id;
}

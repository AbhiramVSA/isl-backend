<script lang="ts">
  import type { Report } from '$lib/types';
  import { statusLabel } from '$lib/types';
  import { relativeTime } from '$lib/time';
  let { report, onPick, busy = false }: { report: Report; onPick?: (report: Report) => void; busy?: boolean } = $props();
  const isAvailable = $derived(report.status === 'NEW' && !report.assigned_officer);
  const assignmentLabel = $derived.by(() => {
    if (isAvailable) return 'Available — choose this report';
    if (report.status === 'RESOLVED') return 'Resolved';
    if (report.assigned_officer) return `${statusLabel[report.status]} — ${report.assigned_officer.name}`;
    return statusLabel[report.status];
  });
</script>

<article class:critical={report.priority === 'CRITICAL'} class:high={report.priority === 'HIGH'}>
  <div class="card-top">
    <span class="priority">{report.priority === 'NORMAL' ? statusLabel[report.status] : `${report.priority} PRIORITY`}</span>
    <span class="time">{relativeTime(report.created_at)}</span>
  </div>
  <div class="assignment" class:available={isAvailable} class:resolved={report.status === 'RESOLVED'}><span class="dot"></span>{assignmentLabel}</div>
  <h3>{report.category}</h3>
  <p>{report.description}</p>
  <div class="card-foot"><span>{report.office.name}</span><div class="card-actions">{#if isAvailable && onPick}<button class="button" disabled={busy} onclick={() => onPick?.(report)}>{busy ? 'Taking report…' : 'Take Report'}</button>{/if}<a class="button secondary" href={`/reports/${report.public_id}`}>View Report</a></div></div>
</article>

<style>
  article{background:white;border:1px solid var(--line);border-left:5px solid var(--blue);border-radius:10px;padding:1rem;display:grid;gap:.6rem;box-shadow:0 2px 6px #153b5010}
  article.high{border-left-color:var(--amber)} article.critical{border-left-color:var(--red)}
  .card-top,.card-foot{display:flex;align-items:center;justify-content:space-between;gap:1rem}.priority{font-size:.76rem;font-weight:800;letter-spacing:.06em;color:var(--blue)}
  .assignment{display:flex;align-items:center;gap:.45rem;width:max-content;max-width:100%;border-radius:999px;background:#edf1f2;color:#44545b;padding:.28rem .6rem;font-size:.78rem;font-weight:750}.assignment.available{background:#e3f3eb;color:#176247}.assignment.resolved{background:#edf1f2;color:#64747b}.dot{width:8px;height:8px;border-radius:50%;background:#78878d;flex:0 0 auto}.available .dot{background:#20825e}.resolved .dot{background:#78878d}.card-actions{display:flex;gap:.5rem;align-items:center}
  .high .priority{color:#8a5100}.critical .priority{color:var(--red)}.time,.card-foot span{color:var(--muted);font-size:.86rem}h3{font-size:1.08rem;margin:0}p{margin:0;color:#3d4a50;display:-webkit-box;line-clamp:2;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  @media(max-width:560px){.card-foot{display:grid;align-items:end}.card-foot>span{max-width:100%}.card-actions{display:grid;grid-template-columns:1fr 1fr}.card-actions .button{padding:.6rem .7rem}}
</style>

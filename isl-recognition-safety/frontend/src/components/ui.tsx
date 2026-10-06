import type { ReactNode } from "react";

export function Panel({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel${className ? ` ${className}` : ""}`}>
      <header className="panel-head">
        <h2>{title}</h2>
        {aside ? <div className="panel-aside">{aside}</div> : null}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

/** Horizontal probability bar. `value` in 0..1. */
export function Bar({
  label,
  value,
  text,
  tone = "data",
  title,
}: {
  label: ReactNode;
  value: number;
  text?: string;
  tone?: "data" | "good" | "warn" | "crit" | "muted";
  title?: string;
}) {
  const w = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0)) * 100;
  return (
    <div className={`bar tone-${tone}`} title={title}>
      <span className="bar-label">{label}</span>
      <span className="bar-track">
        <span className="bar-fill" style={{ width: `${w}%` }} />
      </span>
      <span className="bar-text">{text ?? `${Math.round(w)}%`}</span>
    </div>
  );
}

export function Badge({
  children,
  tone = "muted",
  title,
  pulse,
}: {
  children: ReactNode;
  tone?: "muted" | "good" | "warn" | "crit" | "data" | "info";
  title?: string;
  pulse?: boolean;
}) {
  return (
    <span className={`badge tone-${tone}${pulse ? " pulse" : ""}`} title={title}>
      {children}
    </span>
  );
}

/** Key / value readout row. */
export function Kv({ k, v, title }: { k: ReactNode; v: ReactNode; title?: string }) {
  return (
    <div className="kv" title={title}>
      <span className="kv-k">{k}</span>
      <span className="kv-v">{v}</span>
    </div>
  );
}

export function Dot({ on, label }: { on: boolean; label: string }) {
  return (
    <span className={`dot ${on ? "on" : "off"}`}>
      <i />
      {label}
    </span>
  );
}

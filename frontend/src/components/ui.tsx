import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

/* ------------------------------------------------------------------ data hook */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    fn()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, error, loading, reload, setData };
}

/* ------------------------------------------------------------------ toasts */
type Toast = { id: number; text: string; error?: boolean };
const ToastCtx = createContext<(text: string, error?: boolean) => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, error }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.error ? "error" : ""}`}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/** Wrap an async action with error toasts. */
export function useAction() {
  const toast = useToast();
  return useCallback(
    async <T,>(fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
      try {
        const r = await fn();
        if (success) toast(success);
        return r;
      } catch (e: any) {
        toast(e?.message || String(e), true);
        return undefined;
      }
    },
    [toast],
  );
}

/* ------------------------------------------------------------------ primitives */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, children, full, hint }: { label: string; children: ReactNode; full?: boolean; hint?: string }) {
  return (
    <label className={`field ${full ? "full" : ""}`}>
      {label}
      {children}
      {hint && <span className="muted small">{hint}</span>}
    </label>
  );
}

export function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [text, setText] = useState("");
  const add = () => {
    const parts = text.split(",").map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setText("");
  };
  return (
    <div>
      <div style={{ marginBottom: 4 }}>
        {value.map((t) => (
          <span key={t} className="chip">
            {t}
            <button type="button" onClick={() => onChange(value.filter((x) => x !== t))} aria-label={`Remove ${t}`}>×</button>
          </span>
        ))}
      </div>
      <input
        value={text}
        placeholder={placeholder || "Type and press Enter (comma-separated ok)"}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
      />
    </div>
  );
}

export function ScoreBadge({ score, cls }: { score?: number | null; cls?: string | null }) {
  if (score == null) return <span className="badge">—</span>;
  const c = cls || (score >= 90 ? "EXCELLENT" : score >= 80 ? "STRONG" : score >= 70 ? "GOOD" : score >= 60 ? "MAYBE" : "SKIP");
  return (
    <span className={`badge ${c} score`} title={c}>
      {Math.round(score)}
    </span>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: [T, string][]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs">
      {tabs.map(([k, l]) => (
        <button key={k} className={value === k ? "active" : ""} onClick={() => onChange(k)}>{l}</button>
      ))}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="sm"
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        });
      }}
    >
      {done ? "✓ Copied" : label}
    </button>
  );
}

export function Loading({ error }: { error?: string | null }) {
  return error ? <div className="warnbox">Error: {error}</div> : <div className="muted">Loading…</div>;
}

export function Warnings({ items }: { items?: string[] }) {
  if (!items || !items.length) return null;
  return (
    <div className="warnbox">
      <b>⚠ Verify before sending</b>
      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
        {items.map((w, i) => (
          <li key={i}>{w}</li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ kanban (HTML5 drag & drop) */
export function Kanban<T extends { id: number }>({
  columns,
  render,
  onMove,
}: {
  columns: { key: string; title: string; count?: number; items: T[] }[];
  render: (item: T) => ReactNode;
  onMove: (item: T, toKey: string) => void;
}) {
  const [over, setOver] = useState<string | null>(null);
  const [dragging, setDragging] = useState<{ item: T; from: string } | null>(null);
  return (
    <div className="kanban">
      {columns.map((col) => (
        <div
          key={col.key}
          className={`kcol ${over === col.key ? "over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            if (over !== col.key) setOver(col.key);
          }}
          onDragLeave={() => setOver(null)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(null);
            if (dragging && dragging.from !== col.key) onMove(dragging.item, col.key);
            setDragging(null);
          }}
        >
          <div className="kcol-head">
            <span>{col.title}</span>
            <span className="muted">{col.count ?? col.items.length}</span>
          </div>
          <div className="kcol-body">
            {col.items.map((item) => (
              <div
                key={item.id}
                className="kcard"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.effectAllowed = "move";
                  e.dataTransfer.setData("text/plain", String(item.id));
                  setDragging({ item, from: col.key });
                }}
                onDragEnd={() => setOver(null)}
              >
                {render(item)}
              </div>
            ))}
            {!col.items.length && <div className="muted small" style={{ textAlign: "center", padding: 10 }}>Drop here</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

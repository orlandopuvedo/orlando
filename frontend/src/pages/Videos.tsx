import { useState } from "react";
import { api, fmtDate } from "../api";
import { CopyButton, Empty, Field, Loading, Modal, TagInput, useAction, useApi } from "../components/ui";

function VideoForm({ initial, onSaved }: { initial: any; onSaved: () => void }) {
  const [f, setF] = useState<any>({ platform: "loom", is_active: true, tags: [], ...initial, duration_minutes: initial.duration_seconds ? initial.duration_seconds / 60 : "" });
  const act = useAction();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <div className="col">
      <div className="form-grid">
        <Field label="Video name *"><input value={f.name || ""} onChange={set("name")} placeholder="General Professional Introduction" /></Field>
        <Field label="Platform"><select value={f.platform} onChange={set("platform")}>{["loom", "youtube", "vimeo", "google_drive", "vidyard", "dropbox", "other"].map((p) => <option key={p}>{p}</option>)}</select></Field>
        <Field label="URL" full>
          <div className="row">
            <input className="grow" style={{ flex: 1, width: "auto" }} value={f.url || ""} onChange={set("url")} placeholder="https://www.loom.com/share/…" />
            <button type="button" disabled={!f.url?.includes("loom.com")} onClick={() => act(async () => {
              const m = await api.post("/videos/loom-metadata", { url: f.url });
              if (!m.ok) throw new Error(m.error);
              setF({ ...f, name: f.name || m.title, duration_minutes: m.duration_seconds ? (m.duration_seconds / 60).toFixed(1) : f.duration_minutes });
            }, "Fetched Loom metadata")}>Fetch Loom info</button>
          </div>
        </Field>
        <Field label="Duration (minutes)"><input type="number" step="0.5" value={f.duration_minutes} onChange={set("duration_minutes")} /></Field>
        <Field label="Date created"><input type="date" value={f.date_created || ""} onChange={set("date_created")} /></Field>
        <Field label="Tags (used to match jobs)" full><TagInput value={f.tags || []} onChange={(tags) => setF({ ...f, tags })} placeholder="general, sales, operations, ai…" /></Field>
        <Field label="Description" full><textarea value={f.description || ""} onChange={set("description")} /></Field>
        <Field label="Transcript" full><textarea value={f.transcript || ""} onChange={set("transcript")} /></Field>
        <label className="check"><input type="checkbox" checked={f.is_active} onChange={set("is_active")} /> Active (can be recommended)</label>
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="primary" disabled={!f.name} onClick={async () => {
          const body: any = { ...f, duration_seconds: f.duration_minutes ? Math.round(Number(f.duration_minutes) * 60) : null };
          delete body.duration_minutes;
          for (const k of ["id", "created_at", "updated_at"]) delete body[k];
          if (body.date_created === "") body.date_created = null;
          if (await act(() => (f.id ? api.put(`/videos/${f.id}`, body) : api.post("/videos", body)), "Video saved")) onSaved();
        }}>Save</button>
      </div>
    </div>
  );
}

export default function Videos() {
  const { data, error, reload } = useApi(() => api.get("/videos"));
  const [editing, setEditing] = useState<any>(null);
  const act = useAction();
  return (
    <div>
      <div className="page-head"><h1>Video Library</h1><button className="primary" onClick={() => setEditing({})}>+ Add video</button></div>
      <div className="infobox small" style={{ marginBottom: 12 }}>
        When a job asks for a video (“record a 5-minute video”, “send a Loom”…), the best matching active video is recommended and its link is added to the application package.
        Loom has no public API for submitting videos to job applications, so the app stores and reuses your share links; if an application requires a video <b>file</b> upload, you'll be asked to upload it yourself.
      </div>
      {!data ? <Loading error={error} /> : !data.length ? <Empty>No videos yet.</Empty> : (
        <div className="grid g3">
          {data.map((v: any) => (
            <div key={v.id} className="card">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <b>{v.name}</b>
                <span className={`badge ${v.is_active && v.url ? "good" : ""}`}>{v.is_active ? (v.url ? "active" : "needs URL") : "inactive"}</span>
              </div>
              <div className="small muted">{v.platform} · {v.duration_seconds ? `${Math.round(v.duration_seconds / 60)} min` : "—"} · used {v.times_used}× · {fmtDate(v.date_created)}</div>
              <div style={{ margin: "8px 0" }}>{(v.tags || []).map((t: string) => <span key={t} className="chip">{t}</span>)}</div>
              {v.url ? <div className="row"><a href={v.url} target="_blank" rel="noreferrer" className="small" style={{ overflow: "hidden", textOverflow: "ellipsis", maxWidth: 220 }}>{v.url}</a><CopyButton text={v.url} /></div> : <div className="small warnbox">Add your {v.platform} URL to use this video.</div>}
              {v.description && <div className="small secondary" style={{ marginTop: 6 }}>{v.description}</div>}
              <div className="row" style={{ marginTop: 10 }}>
                <button className="sm" onClick={() => setEditing(v)}>Edit</button>
                <button className="sm" onClick={() => act(() => api.put(`/videos/${v.id}`, { is_active: !v.is_active }).then(reload))}>{v.is_active ? "Deactivate" : "Activate"}</button>
                <button className="sm ghost" onClick={() => confirm("Delete video?") && act(() => api.del(`/videos/${v.id}`).then(reload))}>✕</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {editing && <Modal title={editing.id ? "Edit video" : "Add video"} onClose={() => setEditing(null)} wide><VideoForm initial={editing} onSaved={() => { setEditing(null); reload(); }} /></Modal>}
    </div>
  );
}

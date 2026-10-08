import { useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDate, label } from "../api";
import { CopyButton, Empty, Field, Loading, Modal, Tabs, useAction, useApi } from "../components/ui";

function FollowUpCard({ f, reload }: { f: any; reload: () => void }) {
  const act = useAction();
  const [msg, setMsg] = useState(f.message || "");
  const [busy, setBusy] = useState(false);
  return (
    <div className="card tight">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <b>{f.title}</b> <span className="badge">{label(f.kind)}</span> {f.overdue && <span className="badge critical">overdue</span>} {f.status !== "PENDING" && <span className="badge good">{f.status}</span>}
          <div className="small muted">
            Due {fmtDate(f.due_date)} {f.postponed_count > 0 && `· postponed ${f.postponed_count}×`}
            {f.contact && <> · <Link to={`/contacts/${f.contact.id}`}>{f.contact.full_name}</Link></>}
            {f.job && <> · <Link to={`/jobs/${f.job.id}`}>{f.job.title} — {f.job.company}</Link></>}
          </div>
        </div>
        {f.status === "PENDING" && (
          <div className="row">
            <button className="sm" disabled={busy} onClick={async () => { setBusy(true); const r = await act(() => api.post(`/followups/${f.id}/generate`)); setBusy(false); if (r) setMsg(r.message); }}>✨ {msg ? "Regenerate" : "Generate message"}</button>
            <button className="sm" onClick={() => act(() => api.post(`/followups/${f.id}/postpone`, { days: 2 }).then(reload), "Postponed 2 days")}>Postpone</button>
            <button className="sm good" onClick={() => act(() => api.put(`/followups/${f.id}`, { message: msg }).then(() => api.post(`/followups/${f.id}/sent`)).then(reload), "Marked as sent")}>✓ Mark sent</button>
            <button className="sm ghost" onClick={() => act(() => api.put(`/followups/${f.id}`, { status: "CANCELLED" }).then(reload))}>Dismiss</button>
          </div>
        )}
      </div>
      {(msg || f.status === "PENDING") && (
        <div className="col" style={{ marginTop: 8 }}>
          <textarea value={msg} onChange={(e) => setMsg(e.target.value)} onBlur={() => msg !== (f.message || "") && api.put(`/followups/${f.id}`, { message: msg })} placeholder="Generate or write your follow-up message…" />
          {msg && <div className="row" style={{ justifyContent: "flex-end" }}>
            <CopyButton text={msg} />
            {f.contact?.email && <a className="btn sm" href={`mailto:${f.contact.email}?subject=${encodeURIComponent(f.title)}&body=${encodeURIComponent(msg)}`}>Open in email</a>}
            {f.contact?.linkedin_url && <a className="btn sm" href={f.contact.linkedin_url} target="_blank" rel="noreferrer">Open LinkedIn ↗</a>}
          </div>}
          <div className="small muted">Messages are never sent automatically — copy or open your email client, then mark as sent.</div>
        </div>
      )}
    </div>
  );
}

export default function FollowUps() {
  const [tab, setTab] = useState<"PENDING" | "SENT" | "ALL">("PENDING");
  const { data, error, reload } = useApi(() => api.get(`/followups?status=${tab === "SENT" ? "SENT,DONE" : tab}`), [tab]);
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState<any>({ title: "", due_date: new Date().toISOString().slice(0, 10), kind: "custom" });
  const act = useAction();
  return (
    <div>
      <div className="page-head">
        <h1>Follow-ups</h1>
        <div className="row">
          <button onClick={() => act(() => api.post("/followups/refresh").then((r) => { reload(); return r; }), "Recommendations refreshed")}>↻ Find recommended follow-ups</button>
          <button className="primary" onClick={() => setAdding(true)}>+ Reminder</button>
        </div>
      </div>
      <Tabs tabs={[["PENDING", "To do"], ["SENT", "Sent"], ["ALL", "All"]]} value={tab} onChange={setTab} />
      {!data ? <Loading error={error} /> : !data.length ? <Empty>No follow-ups. Applied jobs, completed interviews and quiet contacts generate recommendations automatically.</Empty> : (
        <div className="col">{data.map((x: any) => <FollowUpCard key={x.id} f={x} reload={reload} />)}</div>
      )}
      {adding && (
        <Modal title="New reminder" onClose={() => setAdding(false)}>
          <div className="col">
            <Field label="Title"><input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
            <Field label="Due"><input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} /></Field>
            <Field label="Message (optional)"><textarea value={f.message || ""} onChange={(e) => setF({ ...f, message: e.target.value })} /></Field>
            <button className="primary" disabled={!f.title} onClick={() => act(() => api.post("/followups", f).then(() => { setAdding(false); reload(); }), "Reminder created")}>Create</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

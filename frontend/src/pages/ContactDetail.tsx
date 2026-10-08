import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fmtDate, fmtDateTime, label } from "../api";
import { CopyButton, Field, Loading, Modal, useAction, useApi } from "../components/ui";
import { CONTACT_STATUSES, ContactForm } from "./Contacts";
import { InterviewForm } from "./Interviews";

const ACTIVITY_TYPES = ["profile_view", "message_received", "message_sent", "email", "call", "screening", "interview", "follow_up", "offer", "rejection", "note"];
const ICON: Record<string, string> = { profile_view: "👀", message_received: "📥", message_sent: "📤", email: "✉", call: "📞", screening: "🔎", interview: "🎤", follow_up: "⏰", offer: "🎉", rejection: "✕", note: "📝" };

export default function ContactDetail() {
  const { id } = useParams();
  const { data: c, error, reload } = useApi(() => api.get(`/contacts/${id}`), [id]);
  const [edit, setEdit] = useState(false);
  const [interview, setInterview] = useState(false);
  const [act_, setAct] = useState<any>({ type: "message_received", summary: "", details: "", occurred_at: new Date().toISOString().slice(0, 16), auto_status: true });
  const act = useAction();
  const nav = useNavigate();
  if (!c) return <Loading error={error} />;
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="page-head">
        <div>
          <div className="small muted"><Link to="/contacts">Contacts</Link></div>
          <h1>{c.full_name}</h1>
          <div className="secondary">{c.job_title || "—"} · {c.company || "—"} {c.job && <>· <Link to={`/jobs/${c.job.id}`}>{c.job.title}</Link></>}</div>
        </div>
        <div className="row">
          <select value={c.status} onChange={(e) => act(() => api.post(`/contacts/${c.id}/status`, { status: e.target.value }).then(reload))} style={{ width: 200 }}>
            {CONTACT_STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
          <button onClick={() => setInterview(true)}>+ Interview</button>
          <button onClick={() => setEdit(true)}>Edit</button>
          <button className="danger" onClick={() => confirm("Delete contact?") && act(() => api.del(`/contacts/${c.id}`)).then(() => nav("/contacts"))}>Delete</button>
        </div>
      </div>
      <div className="grid g-main">
        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <h2>Timeline</h2>
            {!c.activities.length && <div className="muted small">No activity yet — log the first interaction below.</div>}
            <div className="timeline">
              {c.activities.map((a: any) => (
                <div key={a.id} className="tl-item">
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <div><span className="muted small">{fmtDate(a.occurred_at)}</span> &nbsp;{ICON[a.type]} <b>{a.summary}</b> <span className="badge">{label(a.type)}</span></div>
                    <button className="sm ghost" onClick={() => act(() => api.del(`/activities/${a.id}`).then(reload))}>✕</button>
                  </div>
                  {a.details && <div className="small secondary" style={{ whiteSpace: "pre-wrap" }}>{a.details}</div>}
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <h2>Log activity</h2>
            <div className="form-grid">
              <Field label="Type"><select value={act_.type} onChange={(e) => setAct({ ...act_, type: e.target.value })}>{ACTIVITY_TYPES.map((t) => <option key={t} value={t}>{ICON[t]} {label(t)}</option>)}</select></Field>
              <Field label="When"><input type="datetime-local" value={act_.occurred_at} onChange={(e) => setAct({ ...act_, occurred_at: e.target.value })} /></Field>
              <Field label="Summary" full><input value={act_.summary} onChange={(e) => setAct({ ...act_, summary: e.target.value })} placeholder="Recruiter contacted me on LinkedIn" /></Field>
              <Field label="Details / message" full><textarea value={act_.details} onChange={(e) => setAct({ ...act_, details: e.target.value })} /></Field>
              <label className="check"><input type="checkbox" checked={act_.auto_status} onChange={(e) => setAct({ ...act_, auto_status: e.target.checked })} /> Update status automatically</label>
            </div>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="primary" onClick={() => act(() => api.post(`/contacts/${c.id}/activities`, { ...act_, occurred_at: new Date(act_.occurred_at).toISOString() }).then(() => { setAct({ ...act_, summary: "", details: "" }); reload(); }), "Logged")}>Add to timeline</button>
            </div>
          </div>
        </div>
        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <h2>Contact</h2>
            <div className="kv">
              <div>Status</div><div><span className="badge accent">{label(c.status)}</span></div>
              <div>Email</div><div>{c.email ? <span className="row">{c.email}<CopyButton text={c.email} /></span> : "—"}</div>
              <div>Phone</div><div>{c.phone || "—"}</div>
              <div>LinkedIn</div><div>{c.linkedin_url ? <a href={c.linkedin_url} target="_blank" rel="noreferrer">profile ↗</a> : "—"}</div>
              <div>Other</div><div>{c.other_url ? <a href={c.other_url} target="_blank" rel="noreferrer">link ↗</a> : "—"}</div>
              <div>Source</div><div>{c.contact_source || "—"}</div>
              <div>First contact</div><div>{fmtDate(c.first_contact_date)}</div>
              <div>Last contact</div><div>{fmtDate(c.last_contact_date)}</div>
              <div>Next follow-up</div><div>{fmtDate(c.next_follow_up_date)}</div>
              <div>Tags</div><div>{(c.tags || []).map((t: string) => <span key={t} className="chip">{t}</span>)}</div>
            </div>
            {c.notes && <pre className="pre secondary" style={{ marginTop: 10 }}>{c.notes}</pre>}
          </div>
          <div className="card">
            <h2>Interviews</h2>
            {!c.interviews.length && <div className="muted small">None.</div>}
            {c.interviews.map((i: any) => <div key={i.id} className="list-item small">{i.is_final ? "Final" : `#${i.interview_number}`} · {i.interview_type} · {fmtDateTime(i.scheduled_at)} · <span className="badge">{i.status}</span></div>)}
          </div>
          <div className="card">
            <h2>Follow-ups</h2>
            {!c.follow_ups.length && <div className="muted small">None.</div>}
            {c.follow_ups.map((f: any) => <div key={f.id} className="list-item small">{f.title} · {fmtDate(f.due_date)} · <span className="badge">{f.status}</span></div>)}
            <Link to="/followups" className="small">Manage follow-ups →</Link>
          </div>
        </div>
      </div>
      {edit && <Modal title="Edit contact" onClose={() => setEdit(false)} wide><ContactForm initial={c} onSaved={() => { setEdit(false); reload(); }} /></Modal>}
      {interview && <Modal title="Schedule interview" onClose={() => setInterview(false)} wide><InterviewForm initial={{ contact_id: c.id, job_id: c.job?.id, company: c.company }} onSaved={() => { setInterview(false); reload(); }} /></Modal>}
    </div>
  );
}

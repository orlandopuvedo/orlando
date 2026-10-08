import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtDate, label } from "../api";
import { Empty, Field, Kanban, Loading, Modal, TagInput, Tabs, useAction, useApi } from "../components/ui";

export const CONTACT_STATUSES = ["NEW", "PROFILE_VIEWED", "CONTACTED", "REPLIED", "SCREENING", "INTERVIEW_SCHEDULED", "INTERVIEW_1", "INTERVIEW_2", "FINAL_INTERVIEW", "OFFER", "HIRED", "REJECTED", "NO_RESPONSE"];

export function ContactForm({ initial = {}, onSaved }: { initial?: any; onSaved: (c: any) => void }) {
  const [f, setF] = useState<any>({ status: "NEW", tags: [], ...initial });
  const { data: jobs } = useApi(() => api.get("/jobs?limit=500&sort=recent"));
  const act = useAction();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="col">
      <div className="form-grid">
        <Field label="Full name *"><input value={f.full_name || ""} onChange={set("full_name")} /></Field>
        <Field label="Job title"><input value={f.job_title || ""} onChange={set("job_title")} placeholder="Technical Recruiter" /></Field>
        <Field label="Company"><input value={f.company || ""} onChange={set("company")} /></Field>
        <Field label="Status"><select value={f.status} onChange={set("status")}>{CONTACT_STATUSES.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Email"><input value={f.email || ""} onChange={set("email")} /></Field>
        <Field label="Phone"><input value={f.phone || ""} onChange={set("phone")} /></Field>
        <Field label="LinkedIn URL"><input value={f.linkedin_url || ""} onChange={set("linkedin_url")} /></Field>
        <Field label="Other URL"><input value={f.other_url || ""} onChange={set("other_url")} /></Field>
        <Field label="Contact source"><input value={f.contact_source || ""} onChange={set("contact_source")} placeholder="LinkedIn InMail, referral, job post…" /></Field>
        <Field label="Associated job">
          <select value={f.job_id || ""} onChange={(e) => setF({ ...f, job_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">—</option>
            {(jobs?.items || []).map((j: any) => <option key={j.id} value={j.id}>{j.title} — {j.company}</option>)}
          </select>
        </Field>
        <Field label="First contact"><input type="date" value={f.first_contact_date || ""} onChange={set("first_contact_date")} /></Field>
        <Field label="Next follow-up"><input type="date" value={f.next_follow_up_date || ""} onChange={set("next_follow_up_date")} /></Field>
        <Field label="Tags" full><TagInput value={f.tags || []} onChange={(tags) => setF({ ...f, tags })} /></Field>
        <Field label="Notes" full><textarea value={f.notes || ""} onChange={set("notes")} /></Field>
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="primary" disabled={!f.full_name} onClick={async () => {
          const body = { ...f };
          for (const k of Object.keys(body)) if (body[k] === "") body[k] = null;
          const r = await act(() => (f.id ? api.put(`/contacts/${f.id}`, body) : api.post("/contacts", body)), "Contact saved");
          if (r) onSaved(r);
        }}>Save contact</button>
      </div>
    </div>
  );
}

export function ProfileViews() {
  const { data, reload } = useApi(() => api.get("/profile-views"));
  const [f, setF] = useState<any>({ platform: "LinkedIn", viewed_on: new Date().toISOString().slice(0, 10), create_contact: true });
  const act = useAction();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <div className="grid g-main">
      <div className="card table-wrap" style={{ padding: 0 }}>
        <table>
          <thead><tr><th>Date</th><th>Person</th><th>Company</th><th>Platform</th><th>Notes</th><th></th></tr></thead>
          <tbody>
            {(data || []).map((p: any) => (
              <tr key={p.id}>
                <td className="small">{fmtDate(p.viewed_on)}</td>
                <td>{p.contact_id ? <Link to={`/contacts/${p.contact_id}`}>{p.person_name || "contact"}</Link> : p.person_name || <span className="muted">anonymous</span>}<div className="small muted">{p.person_title}</div></td>
                <td>{p.company}</td><td className="small">{p.platform}</td><td className="small">{p.notes}</td>
                <td><button className="sm ghost" onClick={() => act(() => api.del(`/profile-views/${p.id}`).then(reload))}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data?.length && <div className="empty">No profile views recorded.</div>}
      </div>
      <div className="card">
        <h2>Record a profile view</h2>
        <div className="small muted" style={{ marginBottom: 8 }}>Record only what the platform actually shows you. Nothing is guessed.</div>
        <div className="col">
          <Field label="Person (if visible)"><input value={f.person_name || ""} onChange={set("person_name")} /></Field>
          <Field label="Their title"><input value={f.person_title || ""} onChange={set("person_title")} /></Field>
          <Field label="Company"><input value={f.company || ""} onChange={set("company")} /></Field>
          <Field label="Platform"><input value={f.platform} onChange={set("platform")} /></Field>
          <Field label="Date"><input type="date" value={f.viewed_on} onChange={set("viewed_on")} /></Field>
          <Field label="Notes"><textarea value={f.notes || ""} onChange={set("notes")} /></Field>
          <label className="check"><input type="checkbox" checked={f.create_contact} onChange={set("create_contact")} /> Create a contact for this person</label>
          <button className="primary" onClick={() => act(() => api.post("/profile-views", { ...f, create_contact: f.create_contact && !!f.person_name }).then(() => { reload(); setF({ ...f, person_name: "", person_title: "", company: "", notes: "" }); }), "Saved")}>Save</button>
        </div>
      </div>
    </div>
  );
}

const COL_TITLES: Record<string, string> = { NEW: "New", CONTACTED: "Contacted", REPLIED: "Replied", SCREENING: "Screening", INTERVIEW: "Interview", FINAL: "Final", OFFER: "Offer", HIRED: "Hired", CLOSED: "Closed" };

export default function Contacts() {
  const [view, setView] = useState<"board" | "list" | "views">("board");
  const [q, setQ] = useState("");
  const board = useApi(() => api.get("/contacts/pipeline"));
  const list = useApi(() => api.get(`/contacts?q=${encodeURIComponent(q)}`), [q]);
  const [adding, setAdding] = useState(false);
  const act = useAction();
  const nav = useNavigate();
  const reload = () => { board.reload(); list.reload(); };
  return (
    <div>
      <div className="page-head">
        <h1>Contacts <span className="muted small">— recruiters & hiring managers</span></h1>
        <button className="primary" onClick={() => setAdding(true)}>+ Add contact</button>
      </div>
      <Tabs tabs={[["board", "Pipeline"], ["list", "List"], ["views", "Profile views"]]} value={view} onChange={setView} />
      {view === "board" && (!board.data ? <Loading error={board.error} /> : (
        <Kanban
          columns={board.data.columns.map((c: any) => ({ key: c.column, title: COL_TITLES[c.column], items: c.items }))}
          onMove={(c: any, to) => act(() => api.post(`/contacts/${c.id}/status`, { status: to }).then(reload))}
          render={(c: any) => (
            <div>
              <Link className="t" to={`/contacts/${c.id}`}>{c.full_name}</Link>
              <div className="small muted">{c.job_title || "—"} · {c.company || "—"}</div>
              <div className="small"><span className="badge">{label(c.status)}</span> {c.next_follow_up_date && <span className="muted">next {fmtDate(c.next_follow_up_date)}</span>}</div>
            </div>
          )}
        />
      ))}
      {view === "list" && (
        <>
          <input placeholder="Search contacts…" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 10, maxWidth: 360 }} />
          {!list.data ? <Loading error={list.error} /> : !list.data.length ? <Empty>No contacts yet.</Empty> : (
            <div className="card table-wrap" style={{ padding: 0 }}>
              <table>
                <thead><tr><th>Name</th><th>Company</th><th>Status</th><th>Source</th><th>Last contact</th><th>Next follow-up</th></tr></thead>
                <tbody>
                  {list.data.map((c: any) => (
                    <tr key={c.id} className="click" onClick={() => nav(`/contacts/${c.id}`)}>
                      <td><b>{c.full_name}</b><div className="small muted">{c.job_title}</div></td>
                      <td>{c.company}<div className="small muted">{c.job?.title}</div></td>
                      <td><span className="badge">{label(c.status)}</span></td>
                      <td className="small">{c.contact_source}</td>
                      <td className="small">{fmtDate(c.last_contact_date)}</td>
                      <td className="small">{fmtDate(c.next_follow_up_date)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      {view === "views" && <ProfileViews />}
      {adding && <Modal title="Add contact" onClose={() => setAdding(false)} wide><ContactForm onSaved={(c) => { setAdding(false); nav(`/contacts/${c.id}`); }} /></Modal>}
    </div>
  );
}

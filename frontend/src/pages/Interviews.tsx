import { useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime, toLocalInput } from "../api";
import { Empty, Field, Loading, Modal, Tabs, useAction, useApi } from "../components/ui";

const STATUSES = ["SCHEDULED", "COMPLETED", "RESCHEDULED", "CANCELLED", "NO_SHOW"];

export function InterviewForm({ initial = {}, onSaved }: { initial?: any; onSaved: () => void }) {
  const [f, setF] = useState<any>({ interview_type: "video", status: "SCHEDULED", ...initial, scheduled_at: toLocalInput(initial.scheduled_at) });
  const jobs = useApi(() => api.get("/jobs?limit=500&sort=recent"));
  const contacts = useApi(() => api.get("/contacts"));
  const act = useAction();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <div className="col">
      <div className="form-grid">
        <Field label="Job">
          <select value={f.job_id || ""} onChange={(e) => {
            const j = (jobs.data?.items || []).find((x: any) => x.id === Number(e.target.value));
            setF({ ...f, job_id: e.target.value ? Number(e.target.value) : null, company: j?.company || f.company });
          }}>
            <option value="">—</option>{(jobs.data?.items || []).map((j: any) => <option key={j.id} value={j.id}>{j.title} — {j.company}</option>)}
          </select>
        </Field>
        <Field label="Company"><input value={f.company || ""} onChange={set("company")} /></Field>
        <Field label="Contact">
          <select value={f.contact_id || ""} onChange={(e) => setF({ ...f, contact_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">—</option>{(contacts.data || []).map((c: any) => <option key={c.id} value={c.id}>{c.full_name} ({c.company || "—"})</option>)}
          </select>
        </Field>
        <Field label="Type">
          <select value={f.interview_type} onChange={set("interview_type")}>{["screening", "video", "phone", "technical", "behavioral", "panel", "case", "final", "onsite"].map((t) => <option key={t}>{t}</option>)}</select>
        </Field>
        <Field label="Date & time"><input type="datetime-local" value={f.scheduled_at || ""} onChange={set("scheduled_at")} /></Field>
        <Field label="Duration (min)"><input type="number" value={f.duration_minutes || ""} onChange={set("duration_minutes")} /></Field>
        <Field label="Meeting URL"><input value={f.meeting_url || ""} onChange={set("meeting_url")} /></Field>
        <Field label="Interview number" hint="Auto-assigned if empty"><input type="number" value={f.interview_number || ""} onChange={set("interview_number")} /></Field>
        <Field label="Status"><select value={f.status} onChange={set("status")}>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select></Field>
        <label className="check"><input type="checkbox" checked={!!f.is_final} onChange={set("is_final")} /> Final interview</label>
        <Field label="Notes" full><textarea value={f.notes || ""} onChange={set("notes")} /></Field>
        <Field label="Questions asked" full><textarea value={f.questions_asked || ""} onChange={set("questions_asked")} /></Field>
        <Field label="Answers / lessons learned" full><textarea value={f.answers_lessons || ""} onChange={set("answers_lessons")} /></Field>
        <Field label="Next steps"><input value={f.next_steps || ""} onChange={set("next_steps")} /></Field>
        <Field label="Follow-up date"><input type="date" value={f.follow_up_date || ""} onChange={set("follow_up_date")} /></Field>
      </div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="primary" onClick={async () => {
          const body: any = { ...f, scheduled_at: f.scheduled_at ? new Date(f.scheduled_at).toISOString() : null };
          for (const k of ["duration_minutes", "interview_number"]) body[k] = body[k] ? Number(body[k]) : null;
          for (const k of Object.keys(body)) if (body[k] === "") body[k] = null;
          for (const k of ["id", "created_at", "updated_at", "job", "contact", "completed_at"]) delete body[k];
          if (await act(() => (f.id ? api.put(`/interviews/${f.id}`, body) : api.post("/interviews", body)), "Interview saved")) onSaved();
        }}>Save interview</button>
      </div>
    </div>
  );
}

function CompleteForm({ iv, onDone }: { iv: any; onDone: () => void }) {
  const [f, setF] = useState<any>({ notes: iv.notes || "", questions_asked: iv.questions_asked || "", answers_lessons: iv.answers_lessons || "", next_steps: iv.next_steps || "" });
  const act = useAction();
  return (
    <div className="col">
      <Field label="How did it go? (notes)"><textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      <Field label="Questions asked"><textarea value={f.questions_asked} onChange={(e) => setF({ ...f, questions_asked: e.target.value })} /></Field>
      <Field label="Answers / lessons"><textarea value={f.answers_lessons} onChange={(e) => setF({ ...f, answers_lessons: e.target.value })} /></Field>
      <Field label="Next steps"><input value={f.next_steps} onChange={(e) => setF({ ...f, next_steps: e.target.value })} /></Field>
      <div className="small muted">A thank-you note and a follow-up reminder will be created automatically.</div>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="primary" onClick={async () => { if (await act(() => api.post(`/interviews/${iv.id}/complete`, f), "Interview completed")) onDone(); }}>✓ Mark interview completed</button>
      </div>
    </div>
  );
}

export default function Interviews() {
  const [tab, setTab] = useState<"upcoming" | "all">("upcoming");
  const { data, error, reload } = useApi(() => api.get(tab === "upcoming" ? "/interviews?status=SCHEDULED,RESCHEDULED" : "/interviews"), [tab]);
  const [editing, setEditing] = useState<any>(null);
  const [completing, setCompleting] = useState<any>(null);
  const act = useAction();
  return (
    <div>
      <div className="page-head"><h1>Interviews</h1><button className="primary" onClick={() => setEditing({})}>+ Schedule interview</button></div>
      <Tabs tabs={[["upcoming", "Upcoming"], ["all", "All"]]} value={tab} onChange={setTab} />
      {!data ? <Loading error={error} /> : !data.length ? <Empty>No interviews here yet.</Empty> : (
        <div className="col">
          {(tab === "upcoming" ? [...data].sort((a: any, b: any) => (a.scheduled_at || "").localeCompare(b.scheduled_at || "")) : data).map((i: any) => (
            <div key={i.id} className="card tight">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <div>
                  <b>{i.company || "—"}</b> — {i.is_final ? "Final interview" : `Interview #${i.interview_number}`} · {i.interview_type} <span className="badge">{i.status}</span>
                  <div className="small muted">
                    {fmtDateTime(i.scheduled_at)} {i.job && <>· <Link to={`/jobs/${i.job.id}`}>{i.job.title}</Link></>} {i.contact && <>· with <Link to={`/contacts/${i.contact.id}`}>{i.contact.full_name}</Link></>}
                    {i.meeting_url && <> · <a href={i.meeting_url} target="_blank" rel="noreferrer">join ↗</a></>}
                  </div>
                </div>
                <div className="row">
                  {i.status !== "COMPLETED" && <button className="sm good" onClick={() => setCompleting(i)}>✓ Completed</button>}
                  <button className="sm" onClick={() => setEditing(i)}>Edit</button>
                  <button className="sm ghost" onClick={() => confirm("Delete interview?") && act(() => api.del(`/interviews/${i.id}`).then(reload))}>✕</button>
                </div>
              </div>
              {(i.notes || i.answers_lessons || i.next_steps) && (
                <div className="grid g3 small" style={{ marginTop: 8 }}>
                  {i.notes && <div><div className="muted">Notes</div>{i.notes}</div>}
                  {i.answers_lessons && <div><div className="muted">Lessons</div>{i.answers_lessons}</div>}
                  {i.next_steps && <div><div className="muted">Next steps</div>{i.next_steps}</div>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {editing && <Modal title={editing.id ? "Edit interview" : "Schedule interview"} onClose={() => setEditing(null)} wide><InterviewForm initial={editing} onSaved={() => { setEditing(null); reload(); }} /></Modal>}
      {completing && <Modal title={`Complete: ${completing.company || "interview"}`} onClose={() => setCompleting(null)}><CompleteForm iv={completing} onDone={() => { setCompleting(null); reload(); }} /></Modal>}
    </div>
  );
}

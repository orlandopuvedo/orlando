import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fmtDate, label, money } from "../api";
import { Field, Loading, Modal, ScoreBadge, useAction, useApi } from "../components/ui";
import { ContactForm } from "./Contacts";
import { CATEGORIES } from "./Jobs";

const COMPONENT_LABELS: Record<string, string> = {
  salary: "Salary", skills: "Skills", experience: "Experience", role_relevance: "Role relevance", remote_location: "Remote / location",
  education_certifications: "Education / certifications", language: "Language", seniority: "Seniority", application_difficulty: "Application ease",
};

export function ScoreBreakdown({ job }: { job: any }) {
  const comps = job.score_breakdown?.components || {};
  return (
    <div>
      {Object.entries(comps).map(([k, c]: any) => (
        <div key={k} className="funnel-row" style={{ gridTemplateColumns: "170px 1fr 70px" }} title={[...c.reasons, ...c.concerns].join("\n")}>
          <div className="small secondary">{COMPONENT_LABELS[k] || k} <span className="muted">({c.weight}%)</span></div>
          <div className="funnel-track" style={{ height: 12 }}><div className="funnel-fill" style={{ width: `${c.score}%` }} /></div>
          <div className="num small" style={{ textAlign: "right" }}>{Math.round(c.score)}</div>
        </div>
      ))}
      {job.score_breakdown?.caps?.length > 0 && <div className="small warnbox" style={{ marginTop: 8 }}>Score capped: {job.score_breakdown.caps.join(", ")}</div>}
    </div>
  );
}

function EditJob({ job, onClose, onSaved }: { job: any; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<any>({ ...job });
  const act = useAction();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const fields = ["title", "company", "source_url", "apply_url", "location", "salary_min", "salary_max", "salary_currency", "salary_period", "remote_type", "employment_type", "category", "applicants_count"];
  return (
    <Modal title="Edit job" onClose={onClose} wide>
      <div className="form-grid">
        {fields.map((k) => (
          <Field key={k} label={label(k)}>
            {k === "category" ? (
              <select value={f.category || "other"} onChange={set(k)}>{Object.entries(CATEGORIES).map(([a, b]) => <option key={a} value={a}>{b}</option>)}</select>
            ) : k === "remote_type" ? (
              <select value={f.remote_type} onChange={set(k)}>{["remote", "hybrid", "onsite", "unknown"].map((o) => <option key={o}>{o}</option>)}</select>
            ) : (
              <input value={f[k] ?? ""} onChange={set(k)} />
            )}
          </Field>
        ))}
        <label className="check"><input type="checkbox" checked={!!f.easy_apply} onChange={set("easy_apply")} /> Quick / easy apply</label>
        <Field label="Description" full><textarea style={{ minHeight: 220 }} value={f.description || ""} onChange={set("description")} /></Field>
        <Field label="Application questions" full><textarea value={f.application_questions || ""} onChange={set("application_questions")} /></Field>
        <Field label="Notes" full><textarea value={f.notes || ""} onChange={set("notes")} /></Field>
      </div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
        <button className="primary" onClick={async () => {
          const body: any = {};
          for (const k of [...fields, "description", "application_questions", "notes", "easy_apply"]) body[k] = f[k] === "" ? null : f[k];
          for (const k of ["salary_min", "salary_max", "applicants_count"]) body[k] = body[k] == null ? null : Number(body[k]);
          if (await act(() => api.put(`/jobs/${job.id}`, body), "Saved & re-scored")) onSaved();
        }}>Save & re-score</button>
      </div>
    </Modal>
  );
}

export default function JobDetail() {
  const { id } = useParams();
  const { data: job, error, reload } = useApi(() => api.get(`/jobs/${id}`), [id]);
  const [editing, setEditing] = useState(false);
  const [addContact, setAddContact] = useState(false);
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const nav = useNavigate();
  if (!job) return <Loading error={error} />;
  const move = (status: string) => act(() => api.post(`/jobs/${job.id}/status`, { status }).then(reload), `Moved to ${status}`);
  const prepare = async () => {
    setBusy(true);
    const r = await act(() => api.post(`/jobs/${job.id}/application`, {}));
    setBusy(false);
    if (r) nav(`/applications/${r.application_id}`);
  };
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="page-head">
        <div>
          <div className="row"><ScoreBadge score={job.match_score} cls={job.classification} /><h1>{job.title}</h1></div>
          <div className="secondary" style={{ marginTop: 4 }}>
            {job.company || "Unknown company"} · {job.location || "—"} · {job.remote_type} · {label(job.employment_type)} · {CATEGORIES[job.category] || job.category} · {job.seniority}
          </div>
        </div>
        <div className="row">
          <span className="badge">{job.application_status}</span>
          {job.application_id ? (
            <Link className="btn primary" to={`/applications/${job.application_id}`}>Open application →</Link>
          ) : (
            <button className="primary" disabled={busy} onClick={prepare}>{busy ? "Preparing…" : "✨ Prepare application"}</button>
          )}
          <button onClick={() => setEditing(true)}>Edit</button>
          {!["SKIPPED", "APPLIED", "INTERVIEW", "OFFER", "HIRED", "REJECTED"].includes(job.application_status) && <button onClick={() => move("SKIPPED")}>Skip</button>}
          {job.application_status === "SKIPPED" && <button onClick={() => move("QUALIFIED")}>Un-skip</button>}
          <button className="danger" onClick={() => confirm("Delete this job?") && act(() => api.del(`/jobs/${job.id}`)).then(() => nav("/jobs"))}>Delete</button>
        </div>
      </div>

      <div className="grid g-main">
        <div className="col" style={{ gap: 14 }}>
          <div className="grid g2">
            <div className="card">
              <h2>✅ Why this job matches</h2>
              {job.match_reasons.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{job.match_reasons.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul> : <div className="muted">—</div>}
            </div>
            <div className="card">
              <h2>⚠ Potential concerns</h2>
              {job.concerns.length ? <ul style={{ margin: 0, paddingLeft: 18 }}>{job.concerns.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul> : <div className="muted">None detected.</div>}
            </div>
          </div>
          {job.video_required && (
            <div className="card">
              <h2>🎬 Video required</h2>
              <div className="small secondary">Detected: “{job.video_details.phrases?.join("”, “")}” {job.video_details.duration_minutes && `· ~${job.video_details.duration_minutes} min`} · submission: {job.video_details.submission_type}</div>
              {job.video_recommendation ? (
                <div className="goodbox" style={{ marginTop: 8 }}>
                  Recommended: <b>{job.video_recommendation.name}</b>{" "}
                  {job.video_recommendation.url ? <a href={job.video_recommendation.url} target="_blank" rel="noreferrer">{job.video_recommendation.url}</a> : <span className="muted">(no URL yet)</span>}
                </div>
              ) : (
                <div className="warnbox" style={{ marginTop: 8 }}>No active video in your library. <Link to="/videos">Add your Loom video</Link>.</div>
              )}
              {job.video_details.submission_type === "file" && <div className="warnbox" style={{ marginTop: 8 }}>This application needs an uploaded video <b>file</b> — you'll upload it yourself.</div>}
            </div>
          )}
          <div className="card">
            <h2>Description</h2>
            <pre className="pre secondary">{job.description || "No description."}</pre>
            {job.application_questions && (<><h3 style={{ marginTop: 14 }}>Application questions</h3><pre className="pre">{job.application_questions}</pre></>)}
          </div>
        </div>
        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <h2>Match score breakdown</h2>
            <ScoreBreakdown job={job} />
            <div className="small muted" style={{ marginTop: 8 }}>Priority score: <b>{Math.round(job.priority_score || 0)}</b> · weights editable in Settings</div>
          </div>
          <div className="card">
            <h2>Details</h2>
            <div className="kv">
              <div>Salary</div><div>{job.salary_min || job.salary_max ? `${job.salary_currency || ""} ${job.salary_min?.toLocaleString() ?? "?"}–${job.salary_max?.toLocaleString() ?? "?"} / ${job.salary_period}` : "Not listed"}</div>
              <div>Monthly (USD)</div><div>{money(job.salary_monthly_usd_min)} – {money(job.salary_monthly_usd_max)}</div>
              <div>Posted</div><div>{fmtDate(job.posted_at)}</div>
              <div>Discovered</div><div>{fmtDate(job.discovered_at)}</div>
              <div>Apply</div><div>{job.apply_url ? <a href={job.apply_url} target="_blank" rel="noreferrer">Open application page ↗</a> : "—"}</div>
              <div>Listing</div><div>{job.source_url ? <a href={job.source_url} target="_blank" rel="noreferrer">{job.source} ↗</a> : job.source}</div>
              <div>Requirements</div><div className="small">{Object.entries(job.detected_requirements || {}).filter(([k, v]) => v === true && k !== "file_upload").map(([k]) => label(k)).join(", ") || "—"}</div>
            </div>
            {job.refs.length > 1 && (
              <div style={{ marginTop: 10 }}>
                <h3>Seen on {job.refs.length} sources (de-duplicated)</h3>
                {job.refs.map((r: any, i: number) => (
                  <div key={i} className="small">{r.source} {r.url && <a href={r.url} target="_blank" rel="noreferrer">↗</a>} {r.duplicate_reason && <span className="muted">· matched by {r.duplicate_reason}</span>}</div>
                ))}
              </div>
            )}
          </div>
          <div className="card">
            <div className="card-head"><h2>Contacts</h2><button className="sm" onClick={() => setAddContact(true)}>+ Add</button></div>
            {!job.contacts.length && <div className="muted small">No recruiter / hiring manager yet. Adding one raises priority.</div>}
            {job.contacts.map((c: any) => (
              <div key={c.id} className="list-item"><Link to={`/contacts/${c.id}`}>{c.full_name}</Link> <span className="small muted">{c.job_title} · {c.status}</span></div>
            ))}
          </div>
          {job.notes && <div className="card"><h2>Notes</h2><pre className="pre">{job.notes}</pre></div>}
        </div>
      </div>
      {editing && <EditJob job={job} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); reload(); }} />}
      {addContact && (
        <Modal title="Add contact" onClose={() => setAddContact(false)}>
          <ContactForm initial={{ job_id: job.id, company: job.company }} onSaved={() => { setAddContact(false); reload(); }} />
        </Modal>
      )}
    </div>
  );
}

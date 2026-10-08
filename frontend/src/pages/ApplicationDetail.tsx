import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fmtDateTime, label } from "../api";
import { CopyButton, Field, Loading, Modal, Warnings, useAction, useApi } from "../components/ui";
import { ApprovalCard } from "./Approvals";

const NEXT: Record<string, string[]> = {
  READY: ["APPLYING", "SKIPPED"], APPLYING: ["READY", "SKIPPED"], APPLIED: ["FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"],
  FOLLOW_UP: ["INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"], INTERVIEW: ["OFFER", "REJECTED", "WITHDRAWN", "FOLLOW_UP"],
  OFFER: ["HIRED", "REJECTED", "WITHDRAWN"], SKIPPED: ["READY"],
};

function DocEditor({ doc, onSaved }: { doc: any; onSaved: () => void }) {
  const [text, setText] = useState(doc.content);
  const act = useAction();
  return (
    <div className="col">
      <textarea style={{ minHeight: 260 }} value={text} onChange={(e) => setText(e.target.value)} />
      <Warnings items={doc.warnings} />
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="small muted">by {doc.generated_by}{doc.edited ? " · edited" : ""}</span>
        <div className="row">
          <CopyButton text={text} />
          <button className="sm primary" disabled={text === doc.content} onClick={() => act(() => api.put(`/documents/${doc.id}`, { content: text }).then(onSaved), "Saved")}>Save</button>
        </div>
      </div>
    </div>
  );
}

export default function ApplicationDetail() {
  const { id } = useParams();
  const { data: a, error, reload } = useApi(() => api.get(`/applications/${id}`), [id]);
  const act = useAction();
  const [busy, setBusy] = useState("");
  const [agentResult, setAgentResult] = useState<any>(null);
  const [applied, setApplied] = useState(false);
  if (!a) return <Loading error={error} />;
  const pkg = a.package || {};
  const cover = a.documents.find((d: any) => d.kind === "cover_letter" && d.id === a.cover_letter_id) || a.documents.find((d: any) => d.kind === "cover_letter");
  const recruiter = a.documents.find((d: any) => d.kind === "recruiter_message");
  const pending = a.approvals.filter((x: any) => x.status === "PENDING");
  const regen = async (parts: string[], extra: any = {}) => {
    setBusy(parts.join(","));
    await act(() => api.post(`/applications/${a.id}/regenerate`, { parts, ...extra }), "Regenerated");
    setBusy("");
    reload();
  };
  const savePkg = (patch: any) => act(() => api.put(`/applications/${a.id}`, { package: patch }).then(reload));
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="page-head">
        <div>
          <div className="small muted"><Link to="/applications">Applications</Link> / #{a.id}</div>
          <h1>{a.job.title}</h1>
          <div className="secondary">{a.job.company} · <span className="badge">{a.status}</span> · mode <b>{a.mode}</b> {a.applied_at && <>· applied {fmtDateTime(a.applied_at)}</>}</div>
        </div>
        <div className="row">
          {a.job.apply_url && <a className="btn" href={a.job.apply_url} target="_blank" rel="noreferrer">Open application page ↗</a>}
          {["READY", "APPLYING", "SKIPPED"].includes(a.status) && <button className="primary" onClick={() => setApplied(true)}>✓ Mark as applied</button>}
          <select style={{ width: 170 }} value="" onChange={(e) => e.target.value && act(() => api.post(`/applications/${a.id}/transition`, { status: e.target.value }).then(reload), `Moved to ${e.target.value}`)}>
            <option value="">Move to…</option>
            {(NEXT[a.status] || []).map((s) => <option key={s} value={s}>{label(s)}</option>)}
          </select>
        </div>
      </div>

      {pkg.warnings?.length > 0 && <Warnings items={pkg.warnings} />}
      {pending.length > 0 && (
        <div className="card">
          <h2>✅ Needs your approval ({pending.length})</h2>
          <div className="col">{pending.map((ap: any) => <ApprovalCard key={ap.id} ap={ap} onDone={reload} />)}</div>
        </div>
      )}

      <div className="grid g-main">
        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <div className="card-head"><h2>📄 Tailored resume</h2>
              <div className="row">
                <button className="sm" disabled={!!busy} onClick={() => regen(["resume"])}>↻ Regenerate</button>
              </div>
            </div>
            {a.resume_version ? (
              <div className="col">
                <div>{a.resume_version.name} <span className="small muted">· by {a.resume_version.generated_by}</span></div>
                <div className="small muted">Base resume: {pkg.selected_resume?.name || "Master Profile (no uploaded resume)"}</div>
                <div className="row">
                  <a className="btn sm primary" href={`/api/resume-versions/${a.resume_version.id}/download?format=docx`}>⬇ DOCX</a>
                  <a className="btn sm" href={`/api/resume-versions/${a.resume_version.id}/download?format=txt`}>⬇ TXT</a>
                  <a className="btn sm" href={`/api/resume-versions/${a.resume_version.id}/download?format=md`}>⬇ Markdown</a>
                  <Link className="btn sm" to={`/resumes?version=${a.resume_version.id}`}>Edit</Link>
                </div>
                <Warnings items={a.resume_version.warnings} />
              </div>
            ) : <div className="muted">No tailored resume yet. <button className="sm" onClick={() => regen(["resume"])}>Generate</button></div>}
          </div>

          <div className="card">
            <div className="card-head"><h2>✉ Cover letter {pkg.cover_letter?.required && <span className="badge warning">required</span>}</h2>
              <button className="sm" disabled={!!busy} onClick={() => regen(["cover_letter"], { force_cover_letter: true })}>{cover ? "↻ Regenerate" : "Generate"}</button>
            </div>
            {cover ? <DocEditor key={cover.id + cover.updated_at} doc={cover} onSaved={reload} /> : <div className="muted small">Not generated — not required for this job (policy in Settings). Generate one if useful.</div>}
          </div>

          <div className="card">
            <div className="card-head"><h2>💬 Screening answers</h2><button className="sm" disabled={!!busy} onClick={() => regen(["answers"])}>↻ Regenerate</button></div>
            {(pkg.screening_answers || []).map((q: any, i: number) => (
              <div key={i} className="list-item col" style={{ gap: 6 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <b>{q.question}</b>
                  <span className="row">
                    <span className={`badge ${q.needs_approval && !q.approved ? "warning" : ""}`}>{q.kind}{q.needs_approval ? (q.approved ? " · approved" : " · needs approval") : ""}</span>
                    {q.answer && <CopyButton text={q.answer} />}
                  </span>
                </div>
                <textarea defaultValue={q.answer} placeholder="No truthful answer available — write it yourself or add it to the Answer Library."
                  onBlur={(e) => {
                    if (e.target.value === q.answer) return;
                    const answers = [...pkg.screening_answers];
                    answers[i] = { ...q, answer: e.target.value, generated_by: "user" };
                    savePkg({ screening_answers: answers });
                  }} />
                <Warnings items={q.warnings} />
              </div>
            ))}
            <div className="grid g2" style={{ marginTop: 10 }}>
              <div><h3>Salary answer</h3><div className="row"><span className="grow">{pkg.salary_answer || <span className="muted">Set salary in Profile</span>}</span>{pkg.salary_answer && <CopyButton text={pkg.salary_answer} />}</div></div>
              <div><h3>Availability</h3><div className="row"><span className="grow">{pkg.availability_answer || <span className="muted">Set availability in Profile</span>}</span>{pkg.availability_answer && <CopyButton text={pkg.availability_answer} />}</div></div>
            </div>
          </div>

          {recruiter && (
            <div className="card">
              <div className="card-head"><h2>🤝 Recruiter message</h2><button className="sm" disabled={!!busy} onClick={() => regen(["recruiter_message"])}>↻ Regenerate</button></div>
              <DocEditor key={recruiter.id + recruiter.updated_at} doc={recruiter} onSaved={reload} />
            </div>
          )}
        </div>

        <div className="col" style={{ gap: 14 }}>
          <div className="card">
            <h2>Checklist</h2>
            {(pkg.checklist || []).map((c: any, i: number) => (
              <label key={c.key} className="check list-item">
                <input type="checkbox" checked={c.done} onChange={() => {
                  const list = [...pkg.checklist];
                  list[i] = { ...c, done: !c.done };
                  savePkg({ checklist: list });
                }} />
                <span style={{ textDecoration: c.done ? "line-through" : "none" }}>{c.label}</span>
              </label>
            ))}
            <div className="small muted" style={{ marginTop: 8 }}>Generated with {pkg.generated_with}</div>
          </div>

          <div className="card">
            <h2>🎬 Video</h2>
            {pkg.video?.required ? (
              <div className="col">
                <div className="small secondary">Job asks: “{pkg.video.details?.phrases?.join("”, “")}”</div>
                {pkg.video.recommendation ? (
                  <div className="goodbox">
                    <b>{pkg.video.recommendation.name}</b>
                    {pkg.video.recommendation.url ? <div className="row" style={{ marginTop: 4 }}><a href={pkg.video.recommendation.url} target="_blank" rel="noreferrer" className="small">{pkg.video.recommendation.url}</a><CopyButton text={pkg.video.recommendation.url} label="Copy URL" /></div> : <div className="small">Add the URL in the Video Library.</div>}
                  </div>
                ) : <div className="warnbox">No suitable video. <Link to="/videos">Add one</Link>.</div>}
                {pkg.video.details?.submission_type === "file" && <div className="warnbox">Requires uploading a video FILE — do this yourself.</div>}
                {pkg.video.details?.submission_type === "platform" && <div className="warnbox">Uses its own video platform — record it there yourself.</div>}
              </div>
            ) : <div className="muted small">No video required.</div>}
          </div>

          <div className="card">
            <h2>🤖 Application mode</h2>
            <select value={a.mode} onChange={(e) => act(() => api.put(`/applications/${a.id}`, { mode: e.target.value }).then(reload))}>
              <option value="copilot">Copilot — I submit manually</option>
              <option value="supervised">Supervised agent — fills forms, asks before submitting</option>
              <option value="auto">Auto — only where explicitly allowed</option>
            </select>
            {a.mode !== "copilot" && (
              <div className="col" style={{ marginTop: 10 }}>
                <button disabled={busy === "agent"} onClick={async () => {
                  setBusy("agent");
                  setAgentResult(await act(() => api.post(`/applications/${a.id}/agent-run`)));
                  setBusy("");
                  reload();
                }}>{busy === "agent" ? "Agent running… (browser window)" : "▶ Run supervised agent"}</button>
                <div className="small muted">Stops at CAPTCHA, login, 2FA, salary/legal/demographic questions and before final submission.</div>
                {agentResult && <div className={agentResult.status === "submitted" ? "goodbox" : "infobox"}><b>{agentResult.status}</b>: {agentResult.message}</div>}
              </div>
            )}
          </div>

          <div className="card">
            <h2>Details</h2>
            <div className="col">
              <Field label="Application type">
                <select value={a.application_type || ""} onChange={(e) => act(() => api.put(`/applications/${a.id}`, { application_type: e.target.value || null }).then(reload))}>
                  <option value="">—</option>{["easy_apply", "company_site", "job_board", "email", "referral", "recruiter_outreach", "upwork_proposal"].map((t) => <option key={t} value={t}>{label(t)}</option>)}
                </select>
              </Field>
              <Field label="Offer amount (monthly USD)"><input type="number" defaultValue={a.offer_amount_monthly_usd ?? ""} onBlur={(e) => act(() => api.put(`/applications/${a.id}`, { offer_amount_monthly_usd: e.target.value ? Number(e.target.value) : null }).then(reload))} /></Field>
              <Field label="Notes"><textarea defaultValue={a.notes || ""} onBlur={(e) => e.target.value !== (a.notes || "") && act(() => api.put(`/applications/${a.id}`, { notes: e.target.value }).then(reload), "Saved")} /></Field>
              {a.contact && <div className="small">Contact: <Link to={`/contacts/${a.contact.id}`}>{a.contact.full_name}</Link></div>}
            </div>
          </div>

          <div className="card">
            <h2>History</h2>
            <div className="timeline">
              {a.history.map((h: any) => (
                <div key={h.id} className="tl-item small"><b>{h.to_status}</b> <span className="muted">{fmtDateTime(h.created_at)}</span>{h.note && <div className="muted">{h.note}</div>}</div>
              ))}
            </div>
          </div>
        </div>
      </div>
      {applied && <MarkApplied app={a} onClose={() => setApplied(false)} onDone={() => { setApplied(false); reload(); }} />}
    </div>
  );
}

function MarkApplied({ app, onClose, onDone }: { app: any; onClose: () => void; onDone: () => void }) {
  const [type, setType] = useState(app.application_type || (app.job.easy_apply ? "easy_apply" : "company_site"));
  const [via, setVia] = useState(app.job.apply_url || "");
  const act = useAction();
  return (
    <Modal title="Mark as applied" onClose={onClose}>
      <div className="col">
        <Field label="How did you apply?">
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {["easy_apply", "company_site", "job_board", "email", "referral", "recruiter_outreach", "upwork_proposal"].map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
        </Field>
        <Field label="Where (URL / email)"><input value={via} onChange={(e) => setVia(e.target.value)} /></Field>
        <div className="small muted">A follow-up reminder will be scheduled automatically.</div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="primary" onClick={async () => { if (await act(() => api.post(`/applications/${app.id}/mark-applied`, { application_type: type, applied_via: via }), "Marked as applied 🎯")) onDone(); }}>Confirm</button>
        </div>
      </div>
    </Modal>
  );
}

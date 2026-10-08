import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtDate, label, money } from "../api";
import { Empty, Field, Loading, Modal, ScoreBadge, Tabs, useAction, useApi } from "../components/ui";

export const CATEGORIES: Record<string, string> = {
  sales: "Sales / SDR", customer_support: "Customer Support", operations: "Operations", ai_automation: "AI / Automation",
  project_management: "Project Management", admin_assistant: "Admin / Assistant", marketing: "Marketing", engineering: "Engineering",
  data: "Data", finance: "Finance", recruiting_hr: "Recruiting / HR", design: "Design", product: "Product", other: "Other",
};

export function AddJobModal({ onClose, onCreated }: { onClose: () => void; onCreated: (job: any) => void }) {
  const [tab, setTab] = useState<"form" | "url" | "search">("form");
  const [f, setF] = useState<any>({ remote_type: "", employment_type: "" });
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const payload = () => {
    const p: any = { ...f };
    for (const k of ["salary_min", "salary_max", "applicants_count"]) p[k] = p[k] ? Number(p[k]) : null;
    for (const k of Object.keys(p)) if (p[k] === "") delete p[k];
    return p;
  };
  const save = async () => {
    setBusy(true);
    const r = await act(() => api.post("/jobs", payload()));
    setBusy(false);
    if (r) onCreated(r);
  };
  return (
    <Modal title="Add job" onClose={onClose} wide>
      <Tabs tabs={[["form", "Paste / enter job"], ["url", "Import from URL"], ["search", "Search a source"]]} value={tab} onChange={setTab} />
      {tab === "form" && (
        <div className="col">
          <div className="infobox small">Paste the job description from any site (LinkedIn, Indeed, Wellfound…). The system detects salary, remote type, category, video requirements and screening questions automatically.</div>
          <div className="form-grid">
            <Field label="Job title *"><input value={f.title || ""} onChange={set("title")} /></Field>
            <Field label="Company"><input value={f.company || ""} onChange={set("company")} /></Field>
            <Field label="Job URL (where you found it)"><input value={f.source_url || ""} onChange={set("source_url")} placeholder="https://…" /></Field>
            <Field label="Apply URL"><input value={f.apply_url || ""} onChange={set("apply_url")} placeholder="https://…" /></Field>
            <Field label="Source">
              <select value={f.source || "manual"} onChange={set("source")}>
                {["manual", "linkedin", "indeed", "wellfound", "weworkremotely", "remoteco", "remoteok", "remotive", "himalayas", "workingnomads", "justremote", "dynamitejobs", "builtin", "flexjobs", "upwork", "company_site", "referral"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
            <Field label="Location"><input value={f.location || ""} onChange={set("location")} placeholder="Remote — LATAM" /></Field>
            <Field label="Salary min"><input type="number" value={f.salary_min || ""} onChange={set("salary_min")} /></Field>
            <Field label="Salary max"><input type="number" value={f.salary_max || ""} onChange={set("salary_max")} /></Field>
            <Field label="Currency"><input value={f.salary_currency || ""} onChange={set("salary_currency")} placeholder="USD" /></Field>
            <Field label="Salary period">
              <select value={f.salary_period || ""} onChange={set("salary_period")}>
                <option value="">auto-detect</option>{["hour", "day", "week", "month", "year"].map((p) => <option key={p}>{p}</option>)}
              </select>
            </Field>
            <Field label="Work arrangement">
              <select value={f.remote_type} onChange={set("remote_type")}>
                <option value="">auto-detect</option><option value="remote">remote</option><option value="hybrid">hybrid</option><option value="onsite">onsite</option>
              </select>
            </Field>
            <Field label="Employment type">
              <select value={f.employment_type} onChange={set("employment_type")}>
                <option value="">auto-detect</option><option value="full_time">full time</option><option value="part_time">part time</option><option value="contract">contract</option><option value="internship">internship</option>
              </select>
            </Field>
            <Field label="Description *" full><textarea style={{ minHeight: 200 }} value={f.description || ""} onChange={set("description")} /></Field>
            <Field label="Application questions (one per line, optional)" full><textarea value={f.application_questions || ""} onChange={set("application_questions")} placeholder="Why do you want to work here?&#10;What are your salary expectations?" /></Field>
            <label className="check"><input type="checkbox" checked={!!f.easy_apply} onChange={set("easy_apply")} /> Quick / easy apply</label>
            <Field label="Applicants (if shown)"><input type="number" value={f.applicants_count || ""} onChange={set("applicants_count")} /></Field>
          </div>
          {preview && (
            <div className="goodbox small">
              Detected: <b>{CATEGORIES[preview.category] || preview.category}</b> · {preview.remote_type} · {label(preview.employment_type)} · seniority {preview.seniority}
              {preview.salary_monthly_usd_max || preview.salary_monthly_usd_min ? <> · ~{money(preview.salary_monthly_usd_min)}–{money(preview.salary_monthly_usd_max)}/mo</> : " · salary not found"}
              {preview.video_required && <> · 🎬 video required ({preview.video_details.phrases.join(", ")})</>}
              {preview.detected_requirements.screening_questions?.length > 0 && <> · {preview.detected_requirements.screening_questions.length} question(s)</>}
            </div>
          )}
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button onClick={() => act(() => api.post("/jobs/preview", payload()).then(setPreview))} disabled={!f.title}>Preview detection</button>
            <button className="primary" onClick={save} disabled={busy || !f.title}>Save & score</button>
          </div>
        </div>
      )}
      {tab === "url" && (
        <div className="col">
          <div className="infobox small">
            Works with company career pages (Greenhouse, Lever, Ashby and pages with structured job data). LinkedIn, Indeed and other sites
            that prohibit automated access are refused — paste the description instead.
          </div>
          <Field label="Job URL"><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://boards.greenhouse.io/company/jobs/123" /></Field>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="primary" disabled={!url || busy} onClick={async () => {
              setBusy(true);
              const r = await act(() => api.post("/jobs/import-url", { url }));
              setBusy(false);
              if (r) onCreated(r);
            }}>Import</button>
          </div>
        </div>
      )}
      {tab === "search" && <SourceSearch onDone={onClose} />}
    </Modal>
  );
}

function SourceSearch({ onDone }: { onDone: () => void }) {
  const { data: sources } = useApi(() => api.get("/sources"));
  const [key, setKey] = useState("remotive");
  const [q, setQ] = useState("");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const act = useAction();
  const searchable = (sources || []).filter((s: any) => s.automation_status === "allowed");
  return (
    <div className="col">
      <div className="row">
        <select value={key} onChange={(e) => setKey(e.target.value)} style={{ width: 260 }}>
          {searchable.map((s: any) => <option key={s.key} value={s.key}>{s.name}</option>)}
        </select>
        <input className="grow" style={{ width: "auto", flex: 1 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Keywords, e.g. SDR or operations" />
        <button className="primary" disabled={busy} onClick={async () => {
          setBusy(true);
          setResult(await act(() => api.post(`/sources/${key}/search`, { query: q, limit: 40 })));
          setBusy(false);
        }}>{busy ? "Searching…" : "Search"}</button>
      </div>
      {result && <div className="goodbox">Found {result.found} · new {result.created} · duplicates {result.duplicates}. <button className="sm" onClick={onDone}>Close & view jobs</button></div>}
      <div className="muted small">Only sources with an official API / feed are searchable. Company boards need board names in Settings → Sources.</div>
    </div>
  );
}

export default function Jobs() {
  const [filters, setFilters] = useState<any>({ sort: "priority", status: "", min_score: "", q: "", category: "", source: "" });
  const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== "" && v != null) as any).toString();
  const { data, error, reload } = useApi(() => api.get(`/jobs?${qs}&limit=300`), [qs]);
  const [adding, setAdding] = useState(false);
  const nav = useNavigate();
  const act = useAction();
  const set = (k: string) => (e: any) => setFilters({ ...filters, [k]: e.target.value });
  return (
    <div>
      <div className="page-head">
        <h1>Jobs {data && <span className="muted small">({data.total})</span>}</h1>
        <div className="row">
          <button onClick={() => act(() => api.post("/jobs/rescore-all").then(reload), "All jobs re-scored")}>↻ Re-score all</button>
          <button className="primary" onClick={() => setAdding(true)}>+ Add job</button>
        </div>
      </div>
      <div className="card tight row" style={{ marginBottom: 12 }}>
        <input style={{ flex: 2, minWidth: 180 }} placeholder="Search title, company, description…" value={filters.q} onChange={set("q")} />
        <select style={{ width: 150 }} value={filters.status} onChange={set("status")}>
          <option value="">All statuses</option>
          {["DISCOVERED", "QUALIFIED", "READY", "APPLYING", "APPLIED", "FOLLOW_UP", "INTERVIEW", "OFFER", "REJECTED", "SKIPPED"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <select style={{ width: 170 }} value={filters.category} onChange={set("category")}>
          <option value="">All categories</option>
          {Object.entries(CATEGORIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select style={{ width: 130 }} value={filters.min_score} onChange={set("min_score")}>
          <option value="">Any score</option><option value="90">90+ Excellent</option><option value="80">80+ Strong</option><option value="70">70+ Good</option><option value="60">60+ Maybe</option>
        </select>
        <select style={{ width: 140 }} value={filters.sort} onChange={set("sort")}>
          <option value="priority">Sort: priority</option><option value="match">Sort: match</option><option value="salary">Sort: salary</option><option value="recent">Sort: newest found</option><option value="posted">Sort: posted date</option>
        </select>
      </div>
      {!data ? <Loading error={error} /> : !data.items.length ? (
        <Empty>No jobs yet. Click <b>+ Add job</b> to paste one, or enable sources in Settings and run a job hunt.</Empty>
      ) : (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Match</th><th>Job</th><th>Salary /mo</th><th>Category</th><th>Status</th><th>Sources</th><th>Found</th></tr></thead>
            <tbody>
              {data.items.map((j: any) => (
                <tr key={j.id} className="click" onClick={() => nav(`/jobs/${j.id}`)}>
                  <td><ScoreBadge score={j.match_score} cls={j.classification} /><div className="small muted">prio {Math.round(j.priority_score || 0)}</div></td>
                  <td>
                    <b>{j.title}</b> {j.video_required && <span title="Video required">🎬</span>} {j.in_queue && <span className="badge accent">queue</span>}
                    <div className="small muted">{j.company || "—"} · {j.location || j.remote_type}</div>
                  </td>
                  <td className="num">{j.salary_monthly_usd_max || j.salary_monthly_usd_min ? `${money(j.salary_monthly_usd_min)}–${money(j.salary_monthly_usd_max)}` : <span className="muted">n/a</span>}</td>
                  <td className="small">{j.category_label}</td>
                  <td><span className="badge">{j.application_status}</span></td>
                  <td className="small muted">{j.sources.join(", ")}</td>
                  <td className="small muted">{fmtDate(j.discovered_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {adding && (
        <AddJobModal onClose={() => { setAdding(false); reload(); }} onCreated={(r) => {
          setAdding(false);
          if (!r.created) alert(`Duplicate detected (${r.duplicate_reason}) — merged into the existing job.`);
          nav(`/jobs/${r.job.id}`);
        }} />
      )}
      <div className="small muted" style={{ marginTop: 10 }}>Tip: <Link to="/applications">Applications</Link> has the full pipeline Kanban.</div>
    </div>
  );
}

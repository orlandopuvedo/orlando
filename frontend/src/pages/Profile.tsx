import { useEffect, useState } from "react";
import { api, label } from "../api";
import { Field, Loading, Modal, TagInput, Tabs, useAction, useApi } from "../components/ui";
import { CATEGORIES } from "./Jobs";

type Col = { key: string; label: string; type?: "text" | "textarea" | "checkbox" | "tags" | "month" };

function ObjectList({ items, onChange, cols, newItem, title }: { items: any[]; onChange: (v: any[]) => void; cols: Col[]; newItem: any; title: (i: any) => string }) {
  const [open, setOpen] = useState<number | null>(null);
  const update = (i: number, k: string, v: any) => onChange(items.map((it, idx) => (idx === i ? { ...it, [k]: v } : it)));
  return (
    <div className="col">
      {items.map((it, i) => (
        <div key={i} className="card tight">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <b style={{ cursor: "pointer" }} onClick={() => setOpen(open === i ? null : i)}>{title(it) || "(new entry)"} <span className="muted small">{open === i ? "▲" : "▼"}</span></b>
            <div className="row">
              <button className="sm ghost" disabled={i === 0} onClick={() => { const c = [...items]; [c[i - 1], c[i]] = [c[i], c[i - 1]]; onChange(c); }}>↑</button>
              <button className="sm ghost" onClick={() => onChange(items.filter((_, idx) => idx !== i))}>✕</button>
            </div>
          </div>
          {open === i && (
            <div className="form-grid" style={{ marginTop: 10 }}>
              {cols.map((c) => (
                <Field key={c.key} label={c.label} full={c.type === "textarea" || c.type === "tags"}>
                  {c.type === "textarea" ? <textarea value={it[c.key] || ""} onChange={(e) => update(i, c.key, e.target.value)} />
                    : c.type === "checkbox" ? <input type="checkbox" checked={!!it[c.key]} onChange={(e) => update(i, c.key, e.target.checked)} />
                    : c.type === "tags" ? <TagInput value={it[c.key] || []} onChange={(v) => update(i, c.key, v)} placeholder="Press Enter to add" />
                    : <input value={it[c.key] || ""} placeholder={c.type === "month" ? "YYYY-MM" : ""} onChange={(e) => update(i, c.key, e.target.value)} />}
                </Field>
              ))}
            </div>
          )}
        </div>
      ))}
      <button onClick={() => { onChange([...items, { ...newItem }]); setOpen(items.length); }}>+ Add</button>
    </div>
  );
}

function HighlightsEditor({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  return <textarea value={(value || []).join("\n")} onChange={(e) => onChange(e.target.value.split("\n"))} placeholder="One achievement per line (real, verifiable)" />;
}

function ImportModal({ onClose, onApplied }: { onClose: () => void; onApplied: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [proposal, setProposal] = useState<any[] | null>(null);
  const [method, setMethod] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const act = useAction();
  return (
    <Modal title="Import from resume" onClose={onClose} wide>
      {!proposal ? (
        <div className="col">
          <div className="infobox small">The resume is parsed and shown to you field by field. Nothing is saved until you confirm.</div>
          <input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <button className="primary" disabled={!file || busy} onClick={async () => {
            setBusy(true);
            const fd = new FormData();
            fd.append("file", file!);
            const r = await act(() => api.upload("/profile/import", fd));
            setBusy(false);
            if (r) {
              setProposal(r.proposal);
              setMethod(r.method);
              setSelected(Object.fromEntries(r.proposal.map((p: any) => [p.field, p.changed && (p.current == null || p.current === "" || (Array.isArray(p.current) && !p.current.length))])));
            }
          }}>{busy ? "Parsing…" : "Parse resume"}</button>
        </div>
      ) : (
        <div className="col">
          <div className="small muted">Parsed with {method}. Check the fields you want to save. Lists are merged with existing entries.</div>
          {proposal.map((p) => (
            <div key={p.field} className="card tight">
              <label className="check"><input type="checkbox" checked={!!selected[p.field]} onChange={(e) => setSelected({ ...selected, [p.field]: e.target.checked })} /> <b>{label(p.field)}</b> {!p.changed && <span className="badge">same as current</span>}</label>
              <div className="grid g2 small" style={{ marginTop: 6 }}>
                <div><div className="muted">Current</div><pre className="pre mono">{typeof p.current === "string" ? p.current : JSON.stringify(p.current, null, 1)?.slice(0, 1200) || "—"}</pre></div>
                <div><div className="muted">From resume</div><pre className="pre mono">{typeof p.proposed === "string" ? p.proposed : JSON.stringify(p.proposed, null, 1).slice(0, 1200)}</pre></div>
              </div>
            </div>
          ))}
          <div className="row sticky-actions" style={{ justifyContent: "flex-end" }}>
            <button className="primary" onClick={async () => {
              const fields = Object.fromEntries(proposal.filter((p) => selected[p.field]).map((p) => [p.field, p.proposed]));
              if (await act(() => api.post("/profile/import/apply", { fields, merge_lists: true }), "Profile updated")) onApplied();
            }}>Save selected fields</button>
          </div>
        </div>
      )}
    </Modal>
  );
}

export default function Profile() {
  const { data, error, reload } = useApi(() => api.get("/profile"));
  const [p, setP] = useState<any>(null);
  const [tab, setTab] = useState<"personal" | "professional" | "experience" | "background" | "preferences" | "legal">("personal");
  const [importing, setImporting] = useState(false);
  const [dirty, setDirty] = useState(false);
  const act = useAction();
  useEffect(() => { if (data) { setP(data); setDirty(false); } }, [data]);
  if (!p) return <Loading error={error} />;
  const set = (k: string, v: any) => { setP({ ...p, [k]: v }); setDirty(true); };
  const inp = (k: string, placeholder = "") => <input value={p[k] ?? ""} placeholder={placeholder} onChange={(e) => set(k, e.target.value)} />;
  const save = async () => {
    const body = { ...p };
    for (const k of ["id", "created_at", "updated_at", "completeness", "total_experience_years"]) delete body[k];
    for (const k of ["min_salary", "target_salary", "target_salary_max"]) body[k] = body[k] === "" || body[k] == null ? null : Number(body[k]);
    body.work_experience = (body.work_experience || []).map((e: any) => ({ ...e, highlights: (e.highlights || []).filter((h: string) => h.trim()) }));
    if (await act(() => api.put("/profile", body), "Profile saved — jobs re-scored")) reload();
  };
  const toggle = (k: string, v: string) => set(k, (p[k] || []).includes(v) ? p[k].filter((x: string) => x !== v) : [...(p[k] || []), v]);
  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Master Profile</h1>
          <div className="small muted">Your single source of truth. The AI only reorganizes what's here — it never invents. Completeness {p.completeness.percent}% · {p.total_experience_years} years of experience</div>
        </div>
        <div className="row">
          <button onClick={() => setImporting(true)}>⬆ Import from resume</button>
          <button className="primary" disabled={!dirty} onClick={save}>{dirty ? "Save profile" : "Saved"}</button>
        </div>
      </div>
      <Tabs tabs={[["personal", "Personal"], ["professional", "Professional"], ["experience", "Experience"], ["background", "Education & more"], ["preferences", "Job preferences"], ["legal", "Legal / application"]]} value={tab} onChange={setTab} />
      <div className="card">
        {tab === "personal" && (
          <div className="form-grid">
            <Field label="Full name">{inp("full_name")}</Field>
            <Field label="Email">{inp("email")}</Field>
            <Field label="Phone">{inp("phone")}</Field>
            <Field label="Location (city, country)">{inp("location", "Medellín, Colombia")}</Field>
            <Field label="Country">{inp("country", "Colombia")}</Field>
            <Field label="Time zone">{inp("time_zone", "America/Bogota (UTC-5)")}</Field>
            <Field label="LinkedIn URL">{inp("linkedin_url")}</Field>
            <Field label="Portfolio URL">{inp("portfolio_url")}</Field>
            <Field label="Other URLs" full><TagInput value={p.other_urls || []} onChange={(v) => set("other_urls", v)} placeholder="GitHub, website… (Enter)" /></Field>
          </div>
        )}
        {tab === "professional" && (
          <div className="form-grid">
            <Field label="Headline" full>{inp("headline", "Operations & Sales Specialist")}</Field>
            <Field label="Professional summary" full><textarea value={p.professional_summary || ""} onChange={(e) => set("professional_summary", e.target.value)} /></Field>
            <Field label="Skills" full><TagInput value={p.skills || []} onChange={(v) => set("skills", v)} /></Field>
            <Field label="Tools" full><TagInput value={p.tools || []} onChange={(v) => set("tools", v)} /></Field>
            <Field label="Industries" full><TagInput value={p.industries || []} onChange={(v) => set("industries", v)} /></Field>
            <Field label="Achievements (one per line, real & verifiable)" full>
              <textarea value={(p.achievements || []).join("\n")} onChange={(e) => set("achievements", e.target.value.split("\n"))} />
            </Field>
          </div>
        )}
        {tab === "experience" && (
          <ObjectList items={p.work_experience || []} onChange={(v) => set("work_experience", v)}
            title={(e) => [e.title, e.company].filter(Boolean).join(" — ") + (e.start_date ? ` (${e.start_date} – ${e.current ? "present" : e.end_date || "?"})` : "")}
            newItem={{ title: "", company: "", start_date: "", end_date: "", current: false, description: "", highlights: [], skills: [] }}
            cols={[{ key: "title", label: "Job title" }, { key: "company", label: "Company" }, { key: "location", label: "Location" },
              { key: "start_date", label: "Start (YYYY-MM)", type: "month" }, { key: "end_date", label: "End (YYYY-MM)", type: "month" },
              { key: "current", label: "Current job", type: "checkbox" }, { key: "description", label: "Description", type: "textarea" },
              { key: "skills", label: "Skills used", type: "tags" }]} />
        )}
        {tab === "experience" && (p.work_experience || []).length > 0 && (
          <div className="col" style={{ marginTop: 14 }}>
            <h3>Highlights per role (one per line)</h3>
            {(p.work_experience || []).map((e: any, i: number) => (
              <Field key={i} label={`${e.title || "Role"} — ${e.company || ""}`}>
                <HighlightsEditor value={e.highlights || []} onChange={(v) => set("work_experience", p.work_experience.map((x: any, j: number) => (j === i ? { ...x, highlights: v } : x)))} />
              </Field>
            ))}
          </div>
        )}
        {tab === "background" && (
          <div className="grid g2">
            <div><h3>Education</h3><ObjectList items={p.education || []} onChange={(v) => set("education", v)} title={(e) => [e.degree, e.institution].filter(Boolean).join(" — ")}
              newItem={{ institution: "", degree: "", field: "", end_date: "" }}
              cols={[{ key: "institution", label: "Institution" }, { key: "degree", label: "Degree" }, { key: "field", label: "Field" }, { key: "start_date", label: "Start" }, { key: "end_date", label: "End / year" }]} /></div>
            <div><h3>Certifications</h3><ObjectList items={p.certifications || []} onChange={(v) => set("certifications", v)} title={(c) => c.name}
              newItem={{ name: "", issuer: "", date: "", url: "" }} cols={[{ key: "name", label: "Name" }, { key: "issuer", label: "Issuer" }, { key: "date", label: "Date" }, { key: "url", label: "URL" }]} /></div>
            <div><h3>Languages</h3><ObjectList items={p.languages || []} onChange={(v) => set("languages", v)} title={(l) => `${l.language || ""} ${l.proficiency ? `(${l.proficiency})` : ""}`}
              newItem={{ language: "", proficiency: "" }} cols={[{ key: "language", label: "Language" }, { key: "proficiency", label: "Proficiency (Native, C1, B2…)" }]} /></div>
            <div><h3>Projects</h3><ObjectList items={p.projects || []} onChange={(v) => set("projects", v)} title={(x) => x.name}
              newItem={{ name: "", description: "", url: "" }} cols={[{ key: "name", label: "Name" }, { key: "url", label: "URL" }, { key: "description", label: "Description", type: "textarea" }]} /></div>
          </div>
        )}
        {tab === "preferences" && (
          <div className="form-grid">
            <Field label="Minimum salary"><input type="number" value={p.min_salary ?? ""} onChange={(e) => set("min_salary", e.target.value)} /></Field>
            <Field label="Target salary (from)"><input type="number" value={p.target_salary ?? ""} onChange={(e) => set("target_salary", e.target.value)} /></Field>
            <Field label="Target salary (stretch / to)"><input type="number" value={p.target_salary_max ?? ""} onChange={(e) => set("target_salary_max", e.target.value)} /></Field>
            <Field label="Salary currency / period">
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input value={p.salary_currency || "USD"} onChange={(e) => set("salary_currency", e.target.value)} style={{ width: 90 }} />
                <select value={p.salary_period || "month"} onChange={(e) => set("salary_period", e.target.value)}><option value="month">per month</option><option value="year">per year</option><option value="hour">per hour</option></select>
              </div>
            </Field>
            <Field label="Work arrangement" full>
              <div className="row">{["remote", "hybrid", "onsite"].map((w) => <label key={w} className="check"><input type="checkbox" checked={(p.work_arrangements || []).includes(w)} onChange={() => toggle("work_arrangements", w)} />{w}</label>)}</div>
            </Field>
            <Field label="Employment types" full>
              <div className="row">{["full_time", "part_time", "contract", "internship"].map((w) => <label key={w} className="check"><input type="checkbox" checked={(p.employment_types || []).includes(w)} onChange={() => toggle("employment_types", w)} />{label(w)}</label>)}</div>
            </Field>
            <Field label="Preferred roles (job titles)" full><TagInput value={p.preferred_roles || []} onChange={(v) => set("preferred_roles", v)} placeholder="SDR, Operations Specialist, AI Automation Specialist…" /></Field>
            <Field label="Preferred job categories" full>
              <div className="row">{Object.entries(CATEGORIES).filter(([k]) => k !== "other").map(([k, v]) => <label key={k} className="check"><input type="checkbox" checked={(p.preferred_categories || []).includes(k)} onChange={() => toggle("preferred_categories", k)} />{v}</label>)}</div>
            </Field>
            <Field label="Preferred industries" full><TagInput value={p.preferred_industries || []} onChange={(v) => set("preferred_industries", v)} /></Field>
            <Field label="Excluded industries (score capped)" full><TagInput value={p.excluded_industries || []} onChange={(v) => set("excluded_industries", v)} placeholder="gambling, crypto…" /></Field>
            <Field label="Preferred schedules" full><TagInput value={p.preferred_schedules || []} onChange={(v) => set("preferred_schedules", v)} placeholder="US Eastern hours, flexible…" /></Field>
            <Field label="Availability" full>{inp("availability", "I can start within two weeks.")}</Field>
          </div>
        )}
        {tab === "legal" && (
          <div className="form-grid">
            <Field label="Work authorization (your exact situation)" full><textarea value={p.work_authorization || ""} onChange={(e) => set("work_authorization", e.target.value)} placeholder="e.g. Colombian citizen, working as an independent contractor for foreign companies." /></Field>
            <Field label="Requires visa sponsorship?">
              <select value={p.requires_sponsorship == null ? "" : String(p.requires_sponsorship)} onChange={(e) => set("requires_sponsorship", e.target.value === "" ? null : e.target.value === "true")}><option value="">—</option><option value="false">No</option><option value="true">Yes</option></select>
            </Field>
            <Field label="Willing to relocate?">
              <select value={p.willing_to_relocate == null ? "" : String(p.willing_to_relocate)} onChange={(e) => set("willing_to_relocate", e.target.value === "" ? null : e.target.value === "true")}><option value="">—</option><option value="false">No</option><option value="true">Yes</option></select>
            </Field>
            <Field label="Other application preferences" full><textarea value={p.application_preferences || ""} onChange={(e) => set("application_preferences", e.target.value)} /></Field>
            <div className="full small muted">Legal and demographic questions are never answered automatically — they always go through the Approval queue.</div>
          </div>
        )}
      </div>
      {importing && <ImportModal onClose={() => setImporting(false)} onApplied={() => { setImporting(false); reload(); }} />}
    </div>
  );
}

import { useEffect, useState } from "react";
import { api, fmtDateTime, label } from "../api";
import { Field, Loading, TagInput, Tabs, useAction, useApi } from "../components/ui";
import { CATEGORIES } from "./Jobs";

const STATUS_BADGE: Record<string, string> = { allowed: "good", review_required: "warning", manual_only: "critical", unknown: "" };

function Sources() {
  const sources = useApi(() => api.get("/sources"));
  const searches = useApi(() => api.get("/searches"));
  const runs = useApi(() => api.get("/automation/runs?limit=10"));
  const status = useApi(() => api.get("/automation/status"));
  const [q, setQ] = useState("");
  const act = useAction();
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="card">
        <h2>Job sources</h2>
        <div className="small muted" style={{ marginBottom: 8 }}>Only sources with an official API/feed can be searched automatically. No site protections are ever bypassed. Other sources: paste jobs manually.</div>
        {!sources.data ? <Loading /> : (
          <table>
            <thead><tr><th>Source</th><th>Search automation</th><th>Apply automation</th><th>Notes</th><th>Enabled</th></tr></thead>
            <tbody>
              {sources.data.map((s: any) => (
                <tr key={s.key}>
                  <td><b>{s.name}</b><div className="small muted">{s.last_run_at ? `last run ${fmtDateTime(s.last_run_at)}` : ""}{s.last_error && <span style={{ color: "var(--critical)" }}> · {s.last_error}</span>}</div></td>
                  <td><span className={`badge ${STATUS_BADGE[s.automation_status]}`}>{s.automation_status}</span></td>
                  <td><span className={`badge ${STATUS_BADGE[s.apply_automation_status]}`}>{s.apply_automation_status}</span></td>
                  <td className="small secondary" style={{ maxWidth: 420 }}>{s.notes}</td>
                  <td>{s.automation_status === "allowed" ? (
                    <input type="checkbox" checked={s.enabled} onChange={(e) => act(() => api.put(`/sources/${s.key}`, { enabled: e.target.checked }).then(sources.reload))} />
                  ) : <span className="small muted">manual</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="grid g2">
        <div className="card">
          <h2>Saved searches</h2>
          <div className="small muted" style={{ marginBottom: 8 }}>If none are defined, your preferred roles are used as searches.</div>
          {(searches.data || []).map((s: any) => (
            <div key={s.id} className="list-item row" style={{ justifyContent: "space-between" }}>
              <span><b>{s.query || "(all)"}</b> <span className="small muted">{s.sources?.length ? s.sources.join(", ") : "all enabled sources"}</span></span>
              <span className="row">
                <input type="checkbox" checked={s.enabled} onChange={(e) => act(() => api.put(`/searches/${s.id}`, { enabled: e.target.checked }).then(searches.reload))} />
                <button className="sm ghost" onClick={() => act(() => api.del(`/searches/${s.id}`).then(searches.reload))}>✕</button>
              </span>
            </div>
          ))}
          <div className="row" style={{ marginTop: 8, flexWrap: "nowrap" }}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Keywords, e.g. sales development" />
            <button disabled={!q} onClick={() => act(() => api.post("/searches", { query: q }).then(() => { setQ(""); searches.reload(); }))}>Add</button>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Job hunt runs</h2><button className="sm" onClick={() => act(() => api.post("/automation/run").then(() => setTimeout(runs.reload, 3000)), "Started")}>▶ Run now</button></div>
          {status.data && <div className="small muted" style={{ marginBottom: 6 }}>Scheduler {status.data.enabled ? `on · next ${status.data.next_run ? fmtDateTime(status.data.next_run) : "—"}` : "off"}</div>}
          {(runs.data || []).map((r: any) => (
            <div key={r.id} className="list-item small">
              <b>{fmtDateTime(r.started_at)}</b> · {r.trigger} · <span className="badge">{r.status}</span>
              <div className="muted">found {r.stats.found ?? 0} · new {r.stats.new ?? 0} · dupes {r.stats.duplicates ?? 0} · queued {r.stats.queued ?? 0} · packaged {r.stats.packaged ?? 0} · errors {r.stats.errors ?? 0}</div>
            </div>
          ))}
          {!runs.data?.length && <div className="muted small">No runs yet.</div>}
        </div>
      </div>
    </div>
  );
}

export default function Settings() {
  const { data, error, reload } = useApi(() => api.get("/settings"));
  const [s, setS] = useState<any>(null);
  const [tab, setTab] = useState<"general" | "scoring" | "automation" | "sources" | "ai">("general");
  const act = useAction();
  useEffect(() => { if (data) setS(data.settings); }, [data]);
  if (!s || !data) return <Loading error={error} />;
  const set = (k: string, v: any) => setS({ ...s, [k]: v });
  const num = (k: string) => <input type="number" value={s[k]} onChange={(e) => set(k, Number(e.target.value))} />;
  const save = () => act(() => api.put("/settings", s).then(reload), "Settings saved");
  const totalW = Object.values(s.score_weights).reduce((a: number, b: any) => a + Number(b), 0);
  return (
    <div>
      <div className="page-head"><h1>Settings</h1>{tab !== "sources" && <button className="primary" onClick={save}>Save settings</button>}</div>
      <Tabs tabs={[["general", "General"], ["scoring", "Scoring weights"], ["automation", "Automation"], ["sources", "Sources & searches"], ["ai", "AI provider"]]} value={tab} onChange={setTab} />
      {tab === "general" && (
        <div className="card form-grid">
          <div className="full infobox small">Salary minimum / target live in your <a href="/profile">Profile → Job preferences</a> (used by scoring).</div>
          <Field label="Minimum match score to qualify">{num("min_match_score")}</Field>
          <Field label="Minimum score for the Apply Queue">{num("queue_min_score")}</Field>
          <Field label="Daily application target">{num("daily_application_target")}</Field>
          <Field label="Max applications per company">{num("max_applications_per_company")}</Field>
          <Field label="Max applications per source per day">{num("max_applications_per_source_per_day")}</Field>
          <Field label="Notify me for matches ≥">{num("notify_min_match_score")}</Field>
          <Field label="Cover letter policy">
            <select value={s.cover_letter_policy} onChange={(e) => set("cover_letter_policy", e.target.value)}>
              <option value="when_required">Only when required/mentioned</option><option value="when_useful">When useful (strong matches)</option><option value="always">Always</option><option value="never">Never (unless required)</option>
            </select>
          </Field>
          <Field label="Preferred categories (boost role relevance)" full>
            <div className="row">{Object.entries(CATEGORIES).filter(([k]) => k !== "other").map(([k, v]) => <label key={k} className="check"><input type="checkbox" checked={s.preferred_categories.includes(k)} onChange={() => set("preferred_categories", s.preferred_categories.includes(k) ? s.preferred_categories.filter((x: string) => x !== k) : [...s.preferred_categories, k])} />{v}</label>)}</div>
          </Field>
          <Field label="Excluded categories (score capped at 40)" full>
            <div className="row">{Object.entries(CATEGORIES).map(([k, v]) => <label key={k} className="check"><input type="checkbox" checked={s.excluded_categories.includes(k)} onChange={() => set("excluded_categories", s.excluded_categories.includes(k) ? s.excluded_categories.filter((x: string) => x !== k) : [...s.excluded_categories, k])} />{v}</label>)}</div>
          </Field>
          <Field label="Follow-up after application (days)"><input type="number" value={s.follow_up.after_application_days} onChange={(e) => set("follow_up", { ...s.follow_up, after_application_days: Number(e.target.value) })} /></Field>
          <Field label="Thank-you after interview (days)"><input type="number" value={s.follow_up.thank_you_after_interview_days} onChange={(e) => set("follow_up", { ...s.follow_up, thank_you_after_interview_days: Number(e.target.value) })} /></Field>
          <Field label="Follow-up after interview (days)"><input type="number" value={s.follow_up.after_interview_days} onChange={(e) => set("follow_up", { ...s.follow_up, after_interview_days: Number(e.target.value) })} /></Field>
          <Field label="Follow-up contact with no reply (days)"><input type="number" value={s.follow_up.contact_no_reply_days} onChange={(e) => set("follow_up", { ...s.follow_up, contact_no_reply_days: Number(e.target.value) })} /></Field>
        </div>
      )}
      {tab === "scoring" && (
        <div className="grid g2">
          <div className="card">
            <h2>Match score weights <span className="small muted">(total {totalW})</span></h2>
            {Object.entries(s.score_weights).map(([k, v]: any) => (
              <div key={k} className="funnel-row" style={{ gridTemplateColumns: "190px 1fr 60px" }}>
                <span className="small">{label(k)}</span>
                <input type="range" min={0} max={50} value={v} onChange={(e) => set("score_weights", { ...s.score_weights, [k]: Number(e.target.value) })} />
                <span className="num">{v}</span>
              </div>
            ))}
            <button className="sm" onClick={() => set("score_weights", data.defaults.score_weights)}>Reset to defaults</button>
          </div>
          <div className="card">
            <h2>Priority score weights</h2>
            {Object.entries(s.priority_weights).map(([k, v]: any) => (
              <div key={k} className="funnel-row" style={{ gridTemplateColumns: "190px 1fr 60px" }}>
                <span className="small">{label(k)}</span>
                <input type="range" min={0} max={50} value={v} onChange={(e) => set("priority_weights", { ...s.priority_weights, [k]: Number(e.target.value) })} />
                <span className="num">{v}</span>
              </div>
            ))}
            <button className="sm" onClick={() => set("priority_weights", data.defaults.priority_weights)}>Reset to defaults</button>
            <div className="small muted" style={{ marginTop: 8 }}>Saving re-scores every job.</div>
          </div>
        </div>
      )}
      {tab === "automation" && (
        <div className="card form-grid">
          <Field label="Application mode (default for new applications)">
            <select value={s.application_mode} onChange={(e) => set("application_mode", e.target.value)}>
              <option value="copilot">Copilot — AI prepares, I submit</option><option value="supervised">Supervised agent — asks before submitting</option><option value="auto">Auto — only where explicitly allowed</option>
            </select>
          </Field>
          <Field label="Minimum score to auto-build packages">{num("package_min_score")}</Field>
          <label className="check"><input type="checkbox" checked={s.scheduler.enabled} onChange={(e) => set("scheduler", { ...s.scheduler, enabled: e.target.checked })} /> Run the daily job hunt automatically</label>
          <label className="check"><input type="checkbox" checked={s.scheduler.auto_package} onChange={(e) => set("scheduler", { ...s.scheduler, auto_package: e.target.checked })} /> Auto-build packages for high-value jobs</label>
          <Field label="Search times (24h, local time)" full><TagInput value={s.scheduler.times} onChange={(v) => set("scheduler", { ...s.scheduler, times: v.filter((t) => /^\d{2}:\d{2}$/.test(t)) })} placeholder="08:00 (Enter)" /></Field>
          <Field label="Auto-apply permissions" full>
            <div className="small muted">AUTO mode only works for sources whose apply automation status is “allowed”. None of the built-in job boards permit automated applications, so this list is empty by design.</div>
          </Field>
        </div>
      )}
      {tab === "sources" && (
        <div className="col" style={{ gap: 14 }}>
          <div className="card form-grid">
            <div className="full"><h2>Company career boards</h2><div className="small muted">Board names from career-page URLs, e.g. boards.greenhouse.io/<b>gitlab</b>, jobs.lever.co/<b>netflix</b>, jobs.ashbyhq.com/<b>ramp</b>. Save, then enable the source below.</div></div>
            {(["greenhouse", "lever", "ashby"] as const).map((k) => (
              <Field key={k} label={label(k)} full><TagInput value={s.company_boards[k] || []} onChange={(v) => set("company_boards", { ...s.company_boards, [k]: v })} /></Field>
            ))}
            <div className="full"><button className="primary" onClick={save}>Save company boards</button></div>
          </div>
          <Sources />
        </div>
      )}
      {tab === "ai" && (
        <div className="card form-grid">
          <Field label="AI provider">
            <select value={s.ai_provider} onChange={(e) => set("ai_provider", e.target.value)}>
              {data.ai.providers.map((p: string) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="Model (blank = provider default)"><input value={s.ai_model} onChange={(e) => set("ai_model", e.target.value)} placeholder="claude-opus-5-5" /></Field>
          <div className="full">
            <div className={data.ai.available ? "goodbox" : "warnbox"}>
              Active: <b>{data.ai.active}</b> {data.ai.model && `· ${data.ai.model}`} · {data.ai.available ? "available" : "not available — using deterministic templates"}
              <div className="small">API keys are read from environment variables only (never stored in the database): {Object.entries(data.ai.configured_keys).map(([k, v]) => `${k}: ${v ? "✓" : "✗"}`).join(" · ")}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

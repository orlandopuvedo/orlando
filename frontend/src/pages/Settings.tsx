import { useEffect, useState } from "react";
import { api, fmtDateTime, label } from "../api";
import { Field, Loading, Modal, TagInput, Tabs, useAction, useApi } from "../components/ui";
import { HuntSummary, RunHuntButton } from "../components/HuntRun";
import { CATEGORIES } from "./Jobs";

const STATUS_BADGE: Record<string, string> = { allowed: "good", review_required: "warning", manual_only: "critical", unknown: "" };
const HEALTH_BADGE: Record<string, string> = { ok: "good", empty: "warning", error: "critical", never: "" };
const SENIORITY = ["intern", "entry", "junior", "mid", "senior", "lead", "manager", "director", "executive"];

function JobHuntConfig({ settings, onSaved }: { settings: any; onSaved: () => void }) {
  const { data: profile } = useApi(() => api.get("/profile"));
  const [p, setP] = useState<any>(null);
  const [js, setJs] = useState<any>(settings.job_search);
  const [scores, setScores] = useState({ min_match_score: settings.min_match_score, queue_min_score: settings.queue_min_score });
  const [excluded, setExcluded] = useState<string[]>(settings.excluded_categories);
  const act = useAction();
  useEffect(() => { if (profile) setP(profile); }, [profile]);
  if (!p) return <Loading />;
  const setp = (k: string, v: any) => setP({ ...p, [k]: v });
  const toggle = (k: string, v: string) => setp(k, (p[k] || []).includes(v) ? p[k].filter((x: string) => x !== v) : [...(p[k] || []), v]);
  const num = (v: any) => (v === "" || v == null ? null : Number(v));
  const save = () => act(async () => {
    await api.put("/profile", {
      preferred_roles: p.preferred_roles, min_salary: num(p.min_salary), target_salary: num(p.target_salary), max_salary: num(p.max_salary),
      salary_period: p.salary_period, salary_currency: p.salary_currency, work_arrangements: p.work_arrangements,
      employment_types: p.employment_types, preferred_industries: p.preferred_industries, location: p.location, country: p.country,
    });
    await api.put("/settings", { job_search: js, ...scores, excluded_categories: excluded });
    onSaved();
  }, "Job hunt configuration saved — all jobs re-filtered and re-scored");
  return (
    <div className="card form-grid">
      <div className="full infobox small">
        These are <b>hard constraints</b>: a job that violates any of them is never queued, no matter how high it scores.
        Salary is compared after converting both sides to monthly USD.
      </div>
      <Field label="Preferred roles / search queries" full><TagInput value={p.preferred_roles || []} onChange={(v) => setp("preferred_roles", v)} placeholder="SDR, Operations Specialist… (Enter)" /></Field>
      <Field label="Minimum salary"><input type="number" value={p.min_salary ?? ""} onChange={(e) => setp("min_salary", e.target.value)} placeholder="not set" /></Field>
      <Field label="Target salary"><input type="number" value={p.target_salary ?? ""} onChange={(e) => setp("target_salary", e.target.value)} placeholder="not set" /></Field>
      <Field label="Maximum salary">
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input type="number" value={p.max_salary ?? ""} disabled={p.max_salary == null} onChange={(e) => setp("max_salary", e.target.value)} />
          <label className="check"><input type="checkbox" checked={p.max_salary == null} onChange={(e) => setp("max_salary", e.target.checked ? null : p.target_salary || "")} /> No limit</label>
        </div>
      </Field>
      <Field label="Salary period & currency">
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <select value={p.salary_period || "month"} onChange={(e) => setp("salary_period", e.target.value)}><option value="hour">Hourly</option><option value="month">Monthly</option><option value="year">Annual</option></select>
          <input value={p.salary_currency || "USD"} onChange={(e) => setp("salary_currency", e.target.value.toUpperCase())} style={{ width: 90 }} />
        </div>
      </Field>
      <Field label="When salary is not published">
        <select value={js.salary_unknown_policy} onChange={(e) => setJs({ ...js, salary_unknown_policy: e.target.value })}>
          <option value="allow">Allow (mark as unknown)</option><option value="review">Review (don't queue automatically)</option><option value="reject">Reject</option>
        </select>
      </Field>
      <Field label="Work arrangement" full>
        <div className="row">{["remote", "hybrid", "onsite"].map((w) => <label key={w} className="check"><input type="checkbox" checked={(p.work_arrangements || []).includes(w)} onChange={() => toggle("work_arrangements", w)} />{w}</label>)}</div>
      </Field>
      <Field label="Your location"><input value={p.location || ""} onChange={(e) => setp("location", e.target.value)} placeholder="Medellín, Colombia" /></Field>
      <Field label="Your country"><input value={p.country || ""} onChange={(e) => setp("country", e.target.value)} /></Field>
      <Field label="Accepted locations / regions (location restrictions are checked against these)" full>
        <TagInput value={js.locations || []} onChange={(v) => setJs({ ...js, locations: v })} placeholder="Colombia, LATAM, Worldwide…" />
      </Field>
      <Field label="Employment types" full>
        <div className="row">{["full_time", "part_time", "contract", "internship"].map((w) => <label key={w} className="check"><input type="checkbox" checked={(p.employment_types || []).includes(w)} onChange={() => toggle("employment_types", w)} />{label(w)}</label>)}</div>
      </Field>
      <Field label="Seniority (empty = any)" full>
        <div className="row">{SENIORITY.map((w) => <label key={w} className="check"><input type="checkbox" checked={(js.seniority || []).includes(w)} onChange={() => setJs({ ...js, seniority: (js.seniority || []).includes(w) ? js.seniority.filter((x: string) => x !== w) : [...(js.seniority || []), w] })} />{w}</label>)}</div>
      </Field>
      <Field label="Minimum match score to qualify"><input type="number" value={scores.min_match_score} onChange={(e) => setScores({ ...scores, min_match_score: Number(e.target.value) })} /></Field>
      <Field label="Minimum score for the Apply Queue"><input type="number" value={scores.queue_min_score} onChange={(e) => setScores({ ...scores, queue_min_score: Number(e.target.value) })} /></Field>
      <Field label="Excluded companies" full><TagInput value={js.excluded_companies || []} onChange={(v) => setJs({ ...js, excluded_companies: v })} /></Field>
      <Field label="Excluded job types" full>
        <div className="row">{Object.entries(CATEGORIES).map(([k, v]) => <label key={k} className="check"><input type="checkbox" checked={excluded.includes(k)} onChange={() => setExcluded(excluded.includes(k) ? excluded.filter((x) => x !== k) : [...excluded, k])} />{v}</label>)}</div>
      </Field>
      <Field label="Required keywords (ALL must appear)" full><TagInput value={js.required_keywords || []} onChange={(v) => setJs({ ...js, required_keywords: v })} /></Field>
      <Field label="Optional keywords (boost the score)" full><TagInput value={js.optional_keywords || []} onChange={(v) => setJs({ ...js, optional_keywords: v })} /></Field>
      <Field label="Preferred industries (boost the score)" full><TagInput value={p.preferred_industries || []} onChange={(v) => setp("preferred_industries", v)} /></Field>
      <div className="full"><button className="primary" onClick={save}>Save job hunt configuration</button></div>
    </div>
  );
}

function SchedulerStatus() {
  const { data: st, reload } = useApi(() => api.get("/automation/status"));
  useEffect(() => { const t = setInterval(reload, 15000); return () => clearInterval(t); }, [reload]);
  if (!st) return null;
  const last = st.last_run;
  return (
    <div className={st.enabled ? "infobox" : "warnbox"}>
      <b>Scheduler {st.enabled ? "enabled" : "disabled"}</b> · timezone {st.timezone} · {st.running ? "⏳ a job hunt is running now" : "idle"}
      {!st.thread_alive && <> · <span style={{ color: "var(--critical)" }}>scheduler thread not running (SCHEDULER_ENABLED=false?)</span></>}
      <div className="small">Next run: {st.next_run ? fmtDateTime(st.next_run) : "—"}</div>
      {last && <div className="small">Last run: {fmtDateTime(last.started_at)} ({last.trigger}) — <b>{last.status}</b>{last.message ? `: ${last.message}` : ""}</div>}
      {st.last_tick_error && <div className="small" style={{ color: "var(--critical)" }}>Scheduler error: {st.last_tick_error}</div>}
      <div className="small muted">{st.note} Missed runs while offline: at most one catch-up run.</div>
    </div>
  );
}

function Sources() {
  const sources = useApi(() => api.get("/sources"));
  const searches = useApi(() => api.get("/searches"));
  const runs = useApi(() => api.get("/automation/runs?limit=10"));
  const status = useApi(() => api.get("/automation/status"));
  const [q, setQ] = useState("");
  const [openRun, setOpenRun] = useState<any>(null);
  const act = useAction();
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="card">
        <h2>Job sources</h2>
        <div className="small muted" style={{ marginBottom: 8 }}>Only sources with an official API/feed can be searched automatically. No site protections are ever bypassed. Other sources: paste jobs manually.</div>
        {!sources.data ? <Loading /> : (
          <table>
            <thead><tr><th>Source</th><th>Search automation</th><th>Apply automation</th><th>Health</th><th>Notes</th><th>Enabled</th></tr></thead>
            <tbody>
              {sources.data.map((s: any) => (
                <tr key={s.key}>
                  <td><b>{s.name}</b><div className="small muted">{s.last_run_at ? `last run ${fmtDateTime(s.last_run_at)}` : ""}</div></td>
                  <td><span className={`badge ${STATUS_BADGE[s.automation_status]}`}>{s.automation_status}</span></td>
                  <td><span className={`badge ${STATUS_BADGE[s.apply_automation_status]}`}>{s.apply_automation_status}</span></td>
                  <td className="small">
                    <span className={`badge ${HEALTH_BADGE[s.last_status] || ""}`}>{s.last_status || "never"}</span>
                    {s.last_found_count != null && <div className="muted">{s.last_found_count} listings{s.last_success_at ? ` · ok ${fmtDateTime(s.last_success_at)}` : ""}</div>}
                    {s.last_error && <div style={{ color: "var(--critical)" }}>{s.last_error}</div>}
                    {s.automation_status === "allowed" && <button className="sm" style={{ marginTop: 4 }} onClick={() => act(async () => {
                      const r = await api.post(`/sources/${s.key}/test`);
                      sources.reload();
                      if (!r.ok) throw new Error(`${s.name}: ${r.error}`);
                      return r;
                    }, `${s.name}: source responded correctly`)}>Test</button>}
                  </td>
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
          <div className="card-head"><h2>Job hunt runs</h2><RunHuntButton className="sm" onDone={() => { runs.reload(); sources.reload(); }} /></div>
          {status.data && <div className="small muted" style={{ marginBottom: 6 }}>Scheduler {status.data.enabled ? `on · next ${status.data.next_run ? fmtDateTime(status.data.next_run) : "—"}` : "off"}</div>}
          {(runs.data || []).map((r: any) => (
            <div key={r.id} className="list-item small" style={{ cursor: "pointer" }} onClick={() => setOpenRun(r)}>
              <b>{fmtDateTime(r.started_at)}</b> · {r.trigger} · <span className={`badge ${r.status === "failed" ? "critical" : r.status === "completed" ? "good" : "warning"}`}>{r.status}</span>
              {r.message && <div>{r.message}</div>}
              <div className="muted">found {r.stats.found ?? 0} · new {r.stats.new ?? 0} · filtered out {r.stats.rejected_by_filters ?? 0} · dupes {r.stats.duplicates ?? 0} · queued {r.stats.queued ?? 0} · packaged {r.stats.packaged ?? 0} · source errors {r.stats.sources_failed ?? 0}</div>
            </div>
          ))}
          {openRun && <Modal title="Job hunt run" onClose={() => setOpenRun(null)} wide><HuntSummary run={openRun} /></Modal>}
          {!runs.data?.length && <div className="muted small">No runs yet.</div>}
        </div>
      </div>
    </div>
  );
}

export default function Settings() {
  const { data, error, reload } = useApi(() => api.get("/settings"));
  const [s, setS] = useState<any>(null);
  const [tab, setTab] = useState<"jobhunt" | "general" | "scoring" | "automation" | "sources" | "ai">("jobhunt");
  const [aiTest, setAiTest] = useState<any>(null);
  const act = useAction();
  useEffect(() => { if (data) setS(data.settings); }, [data]);
  if (!s || !data) return <Loading error={error} />;
  const set = (k: string, v: any) => setS({ ...s, [k]: v });
  const num = (k: string) => <input type="number" value={s[k]} onChange={(e) => set(k, Number(e.target.value))} />;
  const save = () => act(() => api.put("/settings", s).then(reload), "Settings saved");
  const totalW = Object.values(s.score_weights).reduce((a: number, b: any) => a + Number(b), 0);
  return (
    <div>
      <div className="page-head"><h1>Settings</h1>{tab !== "sources" && tab !== "jobhunt" && <button className="primary" onClick={save}>Save settings</button>}</div>
      <Tabs tabs={[["jobhunt", "Job Hunt"], ["general", "General"], ["scoring", "Scoring weights"], ["automation", "Automation"], ["sources", "Sources & searches"], ["ai", "AI provider"]]} value={tab} onChange={setTab} />
      {tab === "jobhunt" && <JobHuntConfig settings={s} onSaved={reload} />}
      {tab === "general" && (
        <div className="card form-grid">
          <div className="full infobox small">Salary, locations, match thresholds and exclusions are in the <b>Job Hunt</b> tab.</div>
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
          <div className="full"><SchedulerStatus /></div>
          <Field label="Application mode (default for new applications)">
            <select value={s.application_mode} onChange={(e) => set("application_mode", e.target.value)}>
              <option value="copilot">Copilot — AI prepares, I submit</option><option value="supervised">Supervised agent — asks before submitting</option><option value="auto">Auto — only where explicitly allowed</option>
            </select>
          </Field>
          <Field label="Minimum score to auto-build packages">{num("package_min_score")}</Field>
          <Field label="Max form steps per agent run (safety limit)">{num("agent_max_steps")}</Field>
          <Field label="Scheduler timezone (IANA, blank = server local)"><input value={s.scheduler.timezone || ""} placeholder="America/Bogota" onChange={(e) => set("scheduler", { ...s.scheduler, timezone: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={s.scheduler.catch_up !== false} onChange={(e) => set("scheduler", { ...s.scheduler, catch_up: e.target.checked })} /> If runs were missed while the server was off, do one catch-up run</label>
          <div className="full small muted">Final submission always requires your approval in Supervised mode. The scheduler only runs while the backend is running.</div>
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
              {data.ai.last?.last_error && <div className="small" style={{ color: "var(--critical)" }}>Last AI error ({fmtDateTime(data.ai.last.last_error_at)}): {data.ai.last.last_error}</div>}
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={() => act(async () => { setAiTest(null); setAiTest(await api.post("/settings/ai-test")); })}>Test AI provider</button>
              {aiTest && (aiTest.ok ? <span className="badge good">✓ {aiTest.provider} · {aiTest.model} responded in {aiTest.latency_ms} ms</span>
                : <span className="badge critical">✕ {aiTest.error}</span>)}
            </div>
            <div className="small muted" style={{ marginTop: 6 }}>Save first if you changed the provider/model. When AI fails, documents are generated from templates and clearly marked “AI fallback”. Browser actions never depend on AI.</div>
          </div>
        </div>
      )}
    </div>
  );
}

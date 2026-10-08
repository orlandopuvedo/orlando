import { Link } from "react-router-dom";
import { api, compact, fmtDate, fmtDateTime, money, pct } from "../api";
import { Funnel, ProgressBar } from "../components/charts";
import { Loading, ScoreBadge, Stat, useApi } from "../components/ui";

export default function Dashboard() {
  const { data: d, error } = useApi(() => api.get("/dashboard"));
  if (!d) return <Loading error={error} />;
  const m = d.metrics;
  const p = d.progress;
  const todayPct = p.daily_target ? Math.round((p.today_applications / p.daily_target) * 100) : 0;
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="page-head">
        <h1>How close am I to getting the job?</h1>
        <span className="muted small">Updated {fmtDateTime(d.generated_at)}</span>
      </div>

      {d.profile_completeness.percent < 80 && (
        <div className="infobox">
          👋 <b>Start here:</b> your Master Profile is {d.profile_completeness.percent}% complete.{" "}
          <Link to="/profile">Complete your profile</Link> · <Link to="/resumes">upload your resume</Link> ·{" "}
          <Link to="/videos">add your Loom video</Link> · <Link to="/jobs">add jobs</Link>.
        </div>
      )}

      <div className="grid g-main">
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div className="secondary small">Current stage</div>
              <div className="hero">{p.percent}%</div>
              <div style={{ marginTop: 6, fontSize: 16, fontWeight: 600 }}>{p.stage}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="secondary small">Monthly target</div>
              <div style={{ fontSize: 24, fontWeight: 650 }}>{d.salary.monthly_target != null ? `${money(d.salary.monthly_target)}+` : <Link to="/settings">Set it →</Link>}</div>
              {d.salary.target_range[0] != null && <div className="small muted">target {money(d.salary.target_range[0])}{d.salary.target_range[1] ? `–${money(d.salary.target_range[1])}` : "+"} /mo</div>}
            </div>
          </div>
          <div style={{ margin: "14px 0 6px" }}><ProgressBar percent={p.percent} /></div>
          <div className="row small muted" style={{ justifyContent: "space-between" }}>
            <span>Applying</span><span>Responses</span><span>Interviews</span><span>Final</span><span>Offer</span><span>Hired</span>
          </div>
          <div className="grid g3" style={{ marginTop: 16 }}>
            <Stat label="Today's applications" value={`${p.today_applications} / ${p.daily_target}`} sub={<ProgressBar percent={todayPct} />} />
            <Stat label="Current offer value" value={money(d.salary.current_offer_value)}
              sub={d.salary.current_offer_value ? (d.salary.offer_meets_target ? "✅ meets your target" : "below target") : "no offers yet"} />
            <Stat label="Average target salary" value={money(d.salary.average_target_salary)} sub="of jobs applied (monthly USD)" />
          </div>
        </div>
        <div className="card">
          <div className="card-head"><h2>Next actions</h2></div>
          <div className="col" style={{ gap: 8 }}>
            {d.pending_approvals > 0 && <Link className="btn" to="/approvals">✅ {d.pending_approvals} approval(s) waiting</Link>}
            {d.due_follow_ups.length > 0 && <Link className="btn" to="/followups">⏰ {d.due_follow_ups.length} follow-up(s) due</Link>}
            {d.upcoming_interviews.length > 0 && <Link className="btn" to="/interviews">🎤 {d.upcoming_interviews.length} upcoming interview(s)</Link>}
            <Link className="btn" to="/queue">🚀 Apply Queue ({d.queue_size})</Link>
          </div>
          <h3 style={{ marginTop: 16 }}>Recommendations</h3>
          {d.recommendations.length === 0 && <div className="muted small">Nothing to flag — keep going!</div>}
          {d.recommendations.map((r: any, i: number) => (
            <div key={i} className="list-item small">
              <span className={`badge ${r.priority === "high" ? "warning" : ""}`}>{r.type}</span> {r.message}
              {r.detail && <div className="muted">{r.detail}</div>}
            </div>
          ))}
        </div>
      </div>

      <div className="grid g4">
        <Stat label="Jobs found" value={compact(m.jobs_found)} />
        <Stat label="Qualified" value={compact(m.qualified)} />
        <Stat label="Applications" value={compact(m.applications)} />
        <Stat label="Responses" value={compact(m.responses)} sub={`${pct(d.rates.application_success_rate)} response rate`} />
        <Stat label="Contacts" value={compact(m.contacts)} />
        <Stat label="Interviews" value={compact(m.interviews)} sub={`${pct(d.rates.interview_rate)} interview rate`} />
        <Stat label="Final interviews" value={compact(m.final_interviews)} />
        <Stat label="Offers" value={compact(m.offers)} sub={`${pct(d.rates.offer_rate)} offer rate`} />
      </div>

      <div className="grid g2">
        <div className="card">
          <div className="card-head"><h2>Application funnel</h2><Link to="/analytics" className="small">Analytics →</Link></div>
          <Funnel stages={d.funnel} />
        </div>
        <div className="card">
          <div className="card-head"><h2>Top of the Apply Queue</h2><Link to="/queue" className="small">Open queue →</Link></div>
          {!d.queue.length && <div className="empty">Queue is empty. <Link to="/jobs">Add jobs</Link> or run a job hunt.</div>}
          {d.queue.map((j: any) => (
            <div key={j.id} className="list-item row" style={{ justifyContent: "space-between" }}>
              <div style={{ minWidth: 0 }}>
                <Link to={`/jobs/${j.id}`}><b>{j.title}</b></Link>
                <div className="small muted">{j.company || "—"} · {j.salary_max ? money(j.salary_max) + "/mo" : "salary n/a"} {j.video_required && "· 🎬 video"}</div>
              </div>
              <div className="row"><span className="small muted">prio {Math.round(j.priority_score || 0)}</span><ScoreBadge score={j.match_score} cls={j.classification} /></div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h2>Upcoming interviews</h2>
          {!d.upcoming_interviews.length && <div className="muted small">None scheduled.</div>}
          {d.upcoming_interviews.map((i: any) => (
            <div key={i.id} className="list-item">
              <b>{i.company}</b> — {i.is_final ? "Final interview" : `Interview #${i.interview_number}`} ({i.interview_type})
              <div className="small muted">{fmtDateTime(i.scheduled_at)} {i.meeting_url && <a href={i.meeting_url} target="_blank" rel="noreferrer">· join</a>}</div>
            </div>
          ))}
        </div>
        <div className="card">
          <h2>Follow-ups due</h2>
          {!d.due_follow_ups.length && <div className="muted small">You're all caught up.</div>}
          {d.due_follow_ups.map((f: any) => (
            <div key={f.id} className="list-item row" style={{ justifyContent: "space-between" }}>
              <span>{f.title}</span><span className="small muted">{fmtDate(f.due_date)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

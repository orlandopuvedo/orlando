import { useState } from "react";
import { api, money, pct } from "../api";
import { BarChart } from "../components/charts";
import { Loading, Stat, Tabs, useApi } from "../components/ui";

const DIMENSIONS: [string, string][] = [["category", "Job category"], ["source", "Job source"], ["company", "Company"], ["salary_range", "Salary range"],
  ["resume_version", "Resume version"], ["application_type", "Application type"], ["contact_source", "Contact source"]];

export default function Analytics() {
  const { data: a, error } = useApi(() => api.get("/analytics"));
  const [dim, setDim] = useState("category");
  const [period, setPeriod] = useState<"per_day" | "per_week" | "per_month">("per_day");
  if (!a) return <Loading error={error} />;
  const series = a.time_series[period].map((d: any) => ({ label: d.date || d.week || d.month, value: d.count }));
  const rows = a.breakdowns[dim] || [];
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="page-head"><h1>Analytics</h1></div>
      <div className="grid g4">
        <Stat label="Applications" value={a.totals.applications} />
        <Stat label="Response rate" value={pct(a.rates.response_rate)} sub={`${a.totals.responses} responses`} />
        <Stat label="Interview rate" value={pct(a.rates.interview_rate)} sub={`${a.totals.interviews} with interviews`} />
        <Stat label="Offer rate" value={pct(a.rates.offer_rate)} sub={`${a.totals.offers} offers`} />
        <Stat label="Average salary applied" value={money(a.average_salary)} sub="monthly USD" />
        <Stat label="Average match score" value={a.average_match_score ?? "—"} />
      </div>
      <div className="card">
        <div className="card-head">
          <h2>Applications submitted</h2>
          <Tabs tabs={[["per_day", "Per day (30d)"], ["per_week", "Per week (12w)"], ["per_month", "Per month (12m)"]]} value={period} onChange={setPeriod} />
        </div>
        <BarChart data={series} labelEvery={period === "per_day" ? 5 : 2} />
      </div>
      <div className="card">
        <h2>What's working — recommendations</h2>
        {!a.recommendations.length && <div className="muted">Apply to at least 5 jobs per category to unlock learning-based recommendations.</div>}
        {a.recommendations.map((r: any, i: number) => (
          <div key={i} className="list-item"><span className={`badge ${r.type === "increase" ? "good" : r.type === "reduce" ? "warning" : ""}`}>{r.type}</span> <b>{r.message}</b>{r.detail && <div className="small muted">{r.detail}</div>}</div>
        ))}
      </div>
      <div className="card">
        <div className="card-head"><h2>Breakdown</h2>
          <select value={dim} onChange={(e) => setDim(e.target.value)} style={{ width: 220 }}>{DIMENSIONS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>{DIMENSIONS.find((d) => d[0] === dim)?.[1]}</th><th>Applications</th><th>Responses</th><th>Interviews</th><th>Offers</th><th>Response rate</th><th>Interview rate</th><th>Avg match</th></tr></thead>
            <tbody>
              {rows.map((r: any) => (
                <tr key={r.key}>
                  <td><b>{r.label}</b></td><td className="num">{r.applications}</td><td className="num">{r.responses}</td><td className="num">{r.interviews}</td><td className="num">{r.offers}</td>
                  <td className="num">{pct(r.response_rate)}</td>
                  <td>
                    <div className="row" style={{ flexWrap: "nowrap" }}>
                      <div className="funnel-track" style={{ height: 8, width: 80 }}><div className="funnel-fill" style={{ width: `${r.interview_rate * 100}%` }} /></div>
                      <span className="num small">{pct(r.interview_rate)}</span>
                    </div>
                  </td>
                  <td className="num">{r.avg_match ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <div className="empty">No submitted applications yet.</div>}
        </div>
      </div>
    </div>
  );
}

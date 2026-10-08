import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, money } from "../api";
import { Empty, Loading, ScoreBadge, useAction, useApi } from "../components/ui";

export default function ApplyQueue() {
  const { data, error, reload } = useApi(() => api.get("/queue"));
  const [busy, setBusy] = useState<number | null>(null);
  const act = useAction();
  const nav = useNavigate();
  const prepare = async (j: any) => {
    setBusy(j.id);
    const r = await act(() => api.post(`/jobs/${j.id}/application`, {}));
    setBusy(null);
    if (r) nav(`/applications/${r.application_id}`);
  };
  if (!data) return <Loading error={error} />;
  return (
    <div>
      <div className="page-head">
        <h1>Apply Queue <span className="muted small">— highest opportunity first</span></h1>
        <span className="small muted">Jobs above your queue threshold (Settings) that you haven't applied to yet.</span>
      </div>
      {!data.length ? <Empty>Queue is empty. <Link to="/jobs">Add jobs</Link> or run a job hunt.</Empty> : (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>#</th><th>Priority</th><th>Match</th><th>Job</th><th>Salary /mo</th><th>Flags</th><th></th></tr></thead>
            <tbody>
              {data.map((j: any, i: number) => {
                const pb = j.priority_breakdown?.components || {};
                return (
                  <tr key={j.id}>
                    <td className="muted">{i + 1}</td>
                    <td title={Object.entries(pb).map(([k, v]) => `${k}: ${v}`).join("\n")}><b className="num">{Math.round(j.priority_score || 0)}</b></td>
                    <td><ScoreBadge score={j.match_score} cls={j.classification} /></td>
                    <td><Link to={`/jobs/${j.id}`}><b>{j.title}</b></Link><div className="small muted">{j.company} · {j.category_label} · {j.sources.join(", ")}</div></td>
                    <td className="num">{j.salary_monthly_usd_max || j.salary_monthly_usd_min ? money(j.salary_monthly_usd_max || j.salary_monthly_usd_min) : <span className="muted">n/a</span>}</td>
                    <td className="small">
                      {j.video_required && <span className="badge warning">🎬 video</span>} {j.easy_apply && <span className="badge good">quick</span>}{" "}
                      {j.application_status === "READY" && <span className="badge accent">package ready</span>}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <div className="row" style={{ justifyContent: "flex-end" }}>
                        {j.application_id ? <Link className="btn sm primary" to={`/applications/${j.application_id}`}>Open package</Link>
                          : <button className="sm primary" disabled={busy === j.id} onClick={() => prepare(j)}>{busy === j.id ? "Preparing…" : "✨ Prepare"}</button>}
                        <button className="sm" onClick={() => act(() => api.post(`/jobs/${j.id}/status`, { status: "SKIPPED" }).then(reload))}>Skip</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

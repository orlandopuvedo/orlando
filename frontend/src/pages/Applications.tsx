import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtDate, money } from "../api";
import { Kanban, Loading, ScoreBadge, Tabs, useAction, useApi } from "../components/ui";

const TITLES: Record<string, string> = {
  DISCOVERED: "Discovered", QUALIFIED: "Qualified", READY: "Ready", APPLYING: "Applying", SUBMITTED_UNCONFIRMED: "Submitted (unconfirmed)", APPLIED: "Applied",
  FOLLOW_UP: "Follow-up", INTERVIEW: "Interview", OFFER: "Offer", REJECTED: "Rejected",
};

export default function Applications() {
  const [view, setView] = useState<"board" | "list">("board");
  const board = useApi(() => api.get("/pipeline"));
  const list = useApi(() => api.get("/applications"));
  const act = useAction();
  const nav = useNavigate();
  const reload = () => { board.reload(); list.reload(); };
  return (
    <div>
      <div className="page-head">
        <h1>Applications</h1>
        <span className="small muted">Drag cards between columns. Dropping on “Ready” builds the application package.</span>
      </div>
      <Tabs tabs={[["board", "Pipeline board"], ["list", "All applications"]]} value={view} onChange={setView} />
      {view === "board" ? (
        !board.data ? <Loading error={board.error} /> : (
          <Kanban
            columns={board.data.columns.map((c: any) => ({ key: c.status, title: TITLES[c.status], count: c.count, items: c.items }))}
            onMove={(item: any, to) => act(() => api.post(`/jobs/${item.id}/status`, { status: to }).then(reload), `Moved to ${TITLES[to]}`).then(reload)}
            render={(j: any) => (
              <div onDoubleClick={() => nav(j.application_id ? `/applications/${j.application_id}` : `/jobs/${j.id}`)}>
                <div className="row" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
                  <Link className="t" to={j.application_id ? `/applications/${j.application_id}` : `/jobs/${j.id}`}>{j.title}</Link>
                  <ScoreBadge score={j.match_score} cls={j.classification} />
                </div>
                <div className="small muted">{j.company || "—"}</div>
                <div className="small muted">{j.salary_monthly_usd_max ? money(j.salary_monthly_usd_max) + "/mo" : ""} {j.video_required ? "🎬" : ""}</div>
              </div>
            )}
          />
        )
      ) : !list.data ? <Loading error={list.error} /> : (
        <div className="card table-wrap" style={{ padding: 0 }}>
          <table>
            <thead><tr><th>Job</th><th>Status</th><th>Mode</th><th>Applied</th><th>Response</th><th>Match</th></tr></thead>
            <tbody>
              {list.data.map((a: any) => (
                <tr key={a.id} className="click" onClick={() => nav(`/applications/${a.id}`)}>
                  <td><b>{a.job.title}</b><div className="small muted">{a.job.company}</div></td>
                  <td><span className="badge">{a.status}</span></td>
                  <td className="small">{a.mode}</td>
                  <td className="small">{fmtDate(a.applied_at)}</td>
                  <td className="small">{fmtDate(a.response_received_at)}</td>
                  <td><ScoreBadge score={a.job.match_score} cls={a.job.classification} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!list.data.length && <div className="empty">No applications yet.</div>}
        </div>
      )}
    </div>
  );
}

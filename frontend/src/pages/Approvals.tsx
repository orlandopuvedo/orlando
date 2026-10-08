import { useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime } from "../api";
import { Empty, Loading, Tabs, useAction, useApi } from "../components/ui";

const KIND_ICON: Record<string, string> = { salary: "💰", legal: "⚖️", demographic: "🧾", video: "🎬", uncertain: "❓", final_submit: "🚀", blocked: "⛔",
  missing_profile: "👤", video_file: "📼", manual_action: "✋", verify_submission: "🔎" };
const KIND_LABEL: Record<string, string> = { salary: "Salary answer", legal: "Legal / consent", demographic: "Demographic question", video: "Video",
  uncertain: "Uncertain answer", final_submit: "Final submission", blocked: "Agent blocked", missing_profile: "Missing profile info",
  video_file: "Unsupported video upload", manual_action: "Manual action needed", verify_submission: "Verify submission" };

export function ApprovalCard({ ap, onDone }: { ap: any; onDone: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(ap.proposed_value || "");
  const act = useAction();
  const resolve = (action: string, v?: string) => act(() => api.post(`/approvals/${ap.id}/resolve`, { action, value: v }).then(onDone), action === "skip" ? "Skipped" : "Approved");
  const isBlock = ap.kind === "blocked";
  return (
    <div className="card tight">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>{KIND_ICON[ap.kind] || "•"} {ap.title} <span className="badge">{KIND_LABEL[ap.kind] || ap.kind}</span></b>
        <span className="small muted">{fmtDateTime(ap.created_at)}</span>
      </div>
      {ap.message && <div className="secondary" style={{ margin: "6px 0" }}>{ap.message}</div>}
      {ap.job && <div className="small"><Link to={`/jobs/${ap.job.id}`}>{ap.job.title} — {ap.job.company}</Link>{ap.application_id && <> · <Link to={`/applications/${ap.application_id}`}>application</Link></>}</div>}
      {!isBlock && ap.status === "PENDING" && (editing ? (
        <textarea value={value} onChange={(e) => setValue(e.target.value)} style={{ marginTop: 8 }} />
      ) : ap.proposed_value ? (
        <div className="infobox" style={{ marginTop: 8 }}><span className="small muted">Proposed answer:</span><div>{ap.proposed_value}</div></div>
      ) : null)}
      {ap.status === "PENDING" && ap.options?.length > 0 ? (
        <div className="row" style={{ marginTop: 8 }}>
          {ap.options.map((o: string) => (
            <button key={o} className={o === ap.proposed_value ? "good" : ""} onClick={() => resolve("edit", o)}>{o}{o === ap.proposed_value ? " (suggested)" : ""}</button>
          ))}
          {ap.kind !== "verify_submission" && <button onClick={() => resolve("skip")}>SKIP</button>}
        </div>
      ) : ap.status === "PENDING" ? (
        <div className="row" style={{ marginTop: 8 }}>
          {isBlock ? (
            <button className="good" onClick={() => resolve("approve")}>I handled it</button>
          ) : editing ? (
            <button className="primary" onClick={() => resolve("edit", value)}>Save & approve</button>
          ) : (
            <>
              <button className="good" disabled={!ap.proposed_value && ap.kind !== "final_submit"} onClick={() => resolve("approve")}>APPROVE</button>
              {ap.kind !== "final_submit" && <button onClick={() => setEditing(true)}>EDIT</button>}
            </>
          )}
          <button onClick={() => resolve("skip")}>SKIP</button>
        </div>
      ) : (
        <div className="small muted" style={{ marginTop: 6 }}>{ap.status}{ap.final_value ? ` · “${ap.final_value}”` : ""}</div>
      )}
    </div>
  );
}

export default function Approvals() {
  const [status, setStatus] = useState<"PENDING" | "ALL">("PENDING");
  const { data, error, reload } = useApi(() => api.get(`/approvals?status=${status}`), [status]);
  return (
    <div>
      <div className="page-head"><h1>Approval queue</h1><span className="small muted">Nothing sensitive is submitted without you.</span></div>
      <Tabs tabs={[["PENDING", "Pending"], ["ALL", "History"]]} value={status} onChange={setStatus} />
      {!data ? <Loading error={error} /> : !data.length ? <Empty>No approvals waiting. 🎉</Empty> : (
        <div className="col">{data.map((ap: any) => <ApprovalCard key={ap.id} ap={ap} onDone={reload} />)}</div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { api, fmtDateTime } from "../api";
import { Modal, useAction } from "./ui";

const OUTCOME_STYLE: Record<string, string> = {
  ok: "goodbox", only_duplicates: "infobox", no_matching_jobs: "warnbox", no_results: "warnbox", rate_limited: "infobox",
  no_sources_enabled: "warnbox", all_sources_failed: "warnbox", error: "warnbox",
};

export function HuntSummary({ run }: { run: any }) {
  const s = run.stats || {};
  const running = run.status === "running";
  return (
    <div className="col">
      <div className={running ? "infobox" : OUTCOME_STYLE[run.outcome] || "infobox"}>
        <b>{running ? "Running…" : run.status === "failed" ? "Failed" : run.status === "completed_with_errors" ? "Completed with errors" : "Completed"}</b>
        {!running && run.message && <> — {run.message}</>}
        <div className="small muted">{run.trigger} · started {fmtDateTime(run.started_at)}{run.finished_at && ` · finished ${fmtDateTime(run.finished_at)}`}</div>
      </div>
      {!running && (
        <div className="grid g4">
          {[["Sources checked", s.sources_checked], ["Jobs discovered", s.found], ["New", s.new], ["Duplicates removed", s.duplicates],
            ["Rejected by filters", s.rejected_by_filters], ["Needs review (filters)", s.review_by_filters], ["Qualified", s.qualified],
            ["Queued", s.queued], ["Packages created", s.packaged], ["Source errors", s.sources_failed]].map(([l, v]) => (
            <div key={l as string} className="stat"><div className="label">{l}</div><div className="value">{v ?? 0}</div></div>
          ))}
        </div>
      )}
      {s.filter_reasons && Object.keys(s.filter_reasons).length > 0 && (
        <div className="small">Filter rejections: {Object.entries(s.filter_reasons).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}</div>
      )}
      {s.sources && Object.keys(s.sources).length > 0 && (
        <table>
          <thead><tr><th>Source</th><th>Found</th><th>New</th><th>Duplicates</th><th>Status</th></tr></thead>
          <tbody>
            {Object.entries(s.sources).map(([k, v]: any) => (
              <tr key={k}><td>{v.name || k}</td><td>{v.found}</td><td>{v.new}</td><td>{v.duplicates}</td>
                <td className="small">{v.error ? <span style={{ color: "var(--critical)" }}>✕ {v.error}</span> : v.skipped ? <span className="muted">skipped: {v.skipped}</span> : "✓ ok"}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Starts a job hunt and shows its live result summary. */
export function RunHuntButton({ className = "", onDone }: { className?: string; onDone?: () => void }) {
  const [runId, setRunId] = useState<number | null>(null);
  const [run, setRun] = useState<any>(null);
  const act = useAction();
  useEffect(() => {
    if (!runId) return;
    let stop = false;
    const poll = async () => {
      try {
        const r = await api.get(`/automation/runs/${runId}`);
        if (stop) return;
        setRun(r);
        if (r.status === "running") setTimeout(poll, 1500);
        else onDone?.();
      } catch {
        if (!stop) setTimeout(poll, 3000);
      }
    };
    poll();
    return () => { stop = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);
  return (
    <>
      <button className={className} onClick={async () => {
        const r = await act(() => api.post("/automation/run"));
        if (r) { setRun({ status: "running", stats: {}, trigger: "manual", started_at: new Date().toISOString() }); setRunId(r.run_id); }
      }}>▶ Run job hunt</button>
      {run && <Modal title="Job hunt" onClose={() => { setRun(null); setRunId(null); }} wide><HuntSummary run={run} /></Modal>}
    </>
  );
}

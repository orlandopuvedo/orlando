import { useState } from "react";
import { api } from "../api";
import { Empty, Field, Loading, Modal, TagInput, useAction, useApi } from "../components/ui";

export default function Answers() {
  const { data, error, reload } = useApi(() => api.get("/answers"));
  const [editing, setEditing] = useState<any>(null);
  const act = useAction();
  return (
    <div>
      <div className="page-head"><h1>Application Answers</h1><button className="primary" onClick={() => setEditing({ tags: [], requires_approval: false })}>+ Add answer</button></div>
      <div className="infobox small" style={{ marginBottom: 12 }}>
        Write your reusable answers once, in your own words. The engine picks the best match for each screening question and personalizes it
        (you can use <code>{"{company}"}</code> and <code>{"{role}"}</code> placeholders). Empty answers are never used.
      </div>
      {!data ? <Loading error={error} /> : !data.length ? <Empty>No answers yet.</Empty> : (
        <div className="col">
          {data.map((a: any) => (
            <div key={a.id} className="card tight">
              <div className="row" style={{ justifyContent: "space-between" }}>
                <b>{a.question}</b>
                <div className="row">
                  {a.category && <span className="badge">{a.category}</span>}
                  {a.requires_approval && <span className="badge warning">approval</span>}
                  <span className="small muted">used {a.times_used}×</span>
                  <button className="sm" onClick={() => setEditing(a)}>Edit</button>
                  <button className="sm ghost" onClick={() => confirm("Delete?") && act(() => api.del(`/answers/${a.id}`).then(reload))}>✕</button>
                </div>
              </div>
              {a.answer ? <div className="secondary" style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{a.answer}</div> : <div className="warnbox small" style={{ marginTop: 6 }}>Not answered yet — click Edit to write your answer.</div>}
              <div style={{ marginTop: 4 }}>{(a.tags || []).map((t: string) => <span key={t} className="chip">{t}</span>)}</div>
            </div>
          ))}
        </div>
      )}
      {editing && (
        <Modal title={editing.id ? "Edit answer" : "New answer"} onClose={() => setEditing(null)}>
          <div className="col">
            <Field label="Question"><input value={editing.question || ""} onChange={(e) => setEditing({ ...editing, question: e.target.value })} /></Field>
            <Field label="Your answer (truthful, in your words)"><textarea style={{ minHeight: 160 }} value={editing.answer || ""} onChange={(e) => setEditing({ ...editing, answer: e.target.value })} /></Field>
            <Field label="Category">
              <select value={editing.category || ""} onChange={(e) => setEditing({ ...editing, category: e.target.value || null })}>
                <option value="">—</option>{["general", "motivation", "experience", "remote", "salary", "availability", "legal", "demographic"].map((c) => <option key={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Tags"><TagInput value={editing.tags || []} onChange={(tags) => setEditing({ ...editing, tags })} /></Field>
            <label className="check"><input type="checkbox" checked={!!editing.requires_approval} onChange={(e) => setEditing({ ...editing, requires_approval: e.target.checked })} /> Always ask me before using</label>
            <button className="primary" disabled={!editing.question} onClick={async () => {
              const body = { question: editing.question, answer: editing.answer || "", category: editing.category, tags: editing.tags, requires_approval: editing.requires_approval };
              if (await act(() => (editing.id ? api.put(`/answers/${editing.id}`, body) : api.post("/answers", body)), "Saved")) { setEditing(null); reload(); }
            }}>Save</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

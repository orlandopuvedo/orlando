import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, fmtDate } from "../api";
import { Empty, Field, Loading, Modal, TagInput, Warnings, useAction, useApi } from "../components/ui";

function VersionEditor({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: v } = useApi(() => api.get(`/resume-versions/${id}`), [id]);
  const [json, setJson] = useState("");
  const act = useAction();
  useEffect(() => { if (v) setJson(JSON.stringify(v.content, null, 2)); }, [v]);
  if (!v) return null;
  return (
    <Modal title={`Edit: ${v.name}`} onClose={onClose} wide>
      <div className="grid g2">
        <div className="col">
          <h3>Structured content (JSON)</h3>
          <textarea className="mono small" style={{ minHeight: 460 }} value={json} onChange={(e) => setJson(e.target.value)} />
          <div className="small muted">Reorder bullets, remove items or fix wording. Never add facts that aren't true.</div>
        </div>
        <div className="col">
          <h3>Preview</h3>
          <pre className="pre small card" style={{ maxHeight: 460, overflow: "auto" }}>{v.content_text}</pre>
          <Warnings items={v.warnings} />
        </div>
      </div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 10 }}>
        <a className="btn" href={`/api/resume-versions/${id}/download?format=docx`}>⬇ DOCX</a>
        <button className="primary" onClick={() => {
          let content;
          try { content = JSON.parse(json); } catch { alert("Invalid JSON"); return; }
          act(() => api.put(`/resume-versions/${id}`, { content }).then(onClose), "Saved");
        }}>Save</button>
      </div>
    </Modal>
  );
}

export default function Resumes() {
  const resumes = useApi(() => api.get("/resumes"));
  const versions = useApi(() => api.get("/resume-versions"));
  const [params, setParams] = useSearchParams();
  const editId = params.get("version");
  const [upload, setUpload] = useState<any>(null);
  const [viewing, setViewing] = useState<any>(null);
  const [focus, setFocus] = useState("sales");
  const act = useAction();
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="page-head">
        <h1>Resume Library</h1>
        <button className="primary" onClick={() => setUpload({ name: "", focus: "", tags: [], is_default: false, file: null })}>⬆ Upload resume</button>
      </div>
      <div className="card">
        <h2>Uploaded resumes</h2>
        {!resumes.data ? <Loading error={resumes.error} /> : !resumes.data.length ? <Empty>Upload your resume (PDF, DOCX or TXT). Then use <Link to="/profile">Profile → Import</Link> to fill your Master Profile from it.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>Focus / tags</th><th>File</th><th>Used in</th><th>Uploaded</th><th></th></tr></thead>
            <tbody>
              {resumes.data.map((r: any) => (
                <tr key={r.id}>
                  <td><b>{r.name}</b> {r.is_default && <span className="badge accent">default</span>}<div className="small muted">parsed: {r.parsed_data?._method}</div></td>
                  <td className="small">{r.focus} {(r.tags || []).map((t: string) => <span key={t} className="chip">{t}</span>)}</td>
                  <td className="small">{r.original_filename} · {Math.round((r.file_size || 0) / 1024)} KB</td>
                  <td className="small">{r.used_in_applications} application(s)</td>
                  <td className="small">{fmtDate(r.created_at)}</td>
                  <td>
                    <div className="row" style={{ justifyContent: "flex-end" }}>
                      <button className="sm" onClick={() => setViewing(r)}>View parsed</button>
                      <a className="btn sm" href={`/api/resumes/${r.id}/download`}>⬇ Original</a>
                      {!r.is_default && <button className="sm" onClick={() => act(() => api.put(`/resumes/${r.id}`, { is_default: true }).then(resumes.reload))}>Make default</button>}
                      <button className="sm ghost" onClick={() => confirm("Delete resume?") && act(() => api.del(`/resumes/${r.id}`).then(resumes.reload))}>✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <div className="card-head">
          <h2>Tailored resumes</h2>
          <div className="row">
            <select value={focus} onChange={(e) => setFocus(e.target.value)} style={{ width: 200 }}>
              {["sales", "operations", "customer support", "ai automation", "project management", "general"].map((f) => <option key={f}>{f}</option>)}
            </select>
            <button onClick={() => act(() => api.post("/resume-versions", { focus }).then(versions.reload), "Generated from your Master Profile")}>+ Generate focus resume</button>
          </div>
        </div>
        <div className="small muted" style={{ marginBottom: 8 }}>Each job's application package gets its own tailored version (skills & bullets reordered by relevance — never invented).</div>
        {!versions.data ? <Loading /> : !versions.data.length ? <Empty>No tailored versions yet.</Empty> : (
          <table>
            <thead><tr><th>Version</th><th>Focus</th><th>Generated by</th><th>Created</th><th>Download</th><th></th></tr></thead>
            <tbody>
              {versions.data.map((v: any) => (
                <tr key={v.id}>
                  <td><b>{v.name}</b> {v.job_id && <Link className="small" to={`/jobs/${v.job_id}`}>job ↗</Link>} {v.warnings?.length > 0 && <span className="badge warning">{v.warnings.length} to verify</span>}</td>
                  <td className="small">{v.focus}</td><td className="small">{v.generated_by}</td><td className="small">{fmtDate(v.created_at)}</td>
                  <td><div className="row">{["docx", "txt", "md"].map((f) => <a key={f} className="btn sm" href={`/api/resume-versions/${v.id}/download?format=${f}`}>{f}</a>)}</div></td>
                  <td><div className="row"><button className="sm" onClick={() => setParams({ version: String(v.id) })}>Edit</button><button className="sm ghost" onClick={() => act(() => api.del(`/resume-versions/${v.id}`).then(versions.reload))}>✕</button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {upload && (
        <Modal title="Upload resume" onClose={() => setUpload(null)}>
          <div className="col">
            <Field label="File (PDF, DOCX, TXT)"><input type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setUpload({ ...upload, file: e.target.files?.[0] })} /></Field>
            <Field label="Name"><input value={upload.name} onChange={(e) => setUpload({ ...upload, name: e.target.value })} placeholder="Sales-focused resume" /></Field>
            <Field label="Focus"><input value={upload.focus} onChange={(e) => setUpload({ ...upload, focus: e.target.value })} placeholder="sales / operations / ai automation" /></Field>
            <Field label="Tags"><TagInput value={upload.tags} onChange={(tags) => setUpload({ ...upload, tags })} /></Field>
            <label className="check"><input type="checkbox" checked={upload.is_default} onChange={(e) => setUpload({ ...upload, is_default: e.target.checked })} /> Default resume</label>
            <button className="primary" disabled={!upload.file} onClick={async () => {
              const fd = new FormData();
              fd.append("file", upload.file);
              fd.append("name", upload.name);
              fd.append("focus", upload.focus);
              fd.append("tags", upload.tags.join(","));
              fd.append("is_default", String(upload.is_default));
              if (await act(() => api.upload("/resumes", fd), "Resume uploaded & parsed")) { setUpload(null); resumes.reload(); }
            }}>Upload & parse</button>
          </div>
        </Modal>
      )}
      {viewing && (
        <Modal title={`Parsed: ${viewing.name}`} onClose={() => setViewing(null)} wide>
          <div className="infobox small" style={{ marginBottom: 10 }}>This is what was extracted. To use it, go to <Link to="/profile">Profile → Import from resume</Link> and confirm each field.</div>
          <pre className="pre mono small card" style={{ maxHeight: 520, overflow: "auto" }}>{JSON.stringify(viewing.parsed_data, null, 2)}</pre>
        </Modal>
      )}
      {editId && <VersionEditor id={Number(editId)} onClose={() => { setParams({}); versions.reload(); }} />}
    </div>
  );
}

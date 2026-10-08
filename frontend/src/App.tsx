import { useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api, fmtDateTime } from "./api";
import { useAction } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import Jobs from "./pages/Jobs";
import JobDetail from "./pages/JobDetail";
import ApplyQueue from "./pages/ApplyQueue";
import Applications from "./pages/Applications";
import ApplicationDetail from "./pages/ApplicationDetail";
import Contacts from "./pages/Contacts";
import ContactDetail from "./pages/ContactDetail";
import Interviews from "./pages/Interviews";
import FollowUps from "./pages/FollowUps";
import Resumes from "./pages/Resumes";
import Videos from "./pages/Videos";
import Answers from "./pages/Answers";
import Profile from "./pages/Profile";
import Analytics from "./pages/Analytics";
import Settings from "./pages/Settings";
import Approvals from "./pages/Approvals";

const NAV: ([string, string, string] | null)[] = [
  ["/", "Dashboard", "📊"],
  ["/jobs", "Jobs", "🔎"],
  ["/queue", "Apply Queue", "🚀"],
  ["/applications", "Applications", "📨"],
  ["/approvals", "Approvals", "✅"],
  null,
  ["/contacts", "Contacts", "👥"],
  ["/interviews", "Interviews", "🎤"],
  ["/followups", "Follow-ups", "⏰"],
  null,
  ["/resumes", "Resumes", "📄"],
  ["/videos", "Videos", "🎬"],
  ["/answers", "Answers", "💬"],
  ["/profile", "Profile", "👤"],
  null,
  ["/analytics", "Analytics", "📈"],
  ["/settings", "Settings", "⚙️"],
];

function Notifications() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ unread: number; items: any[] }>({ unread: 0, items: [] });
  const nav = useNavigate();
  const ref = useRef<HTMLDivElement>(null);
  const load = () => api.get("/notifications?limit=40").then(setData).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => {
      clearInterval(t);
      document.removeEventListener("mousedown", close);
    };
  }, []);
  const icon: Record<string, string> = {
    high_match_job: "🎯", recruiter_contact: "💬", interview_upcoming: "🎤", follow_up_due: "⏰", application_blocked: "⛔",
    video_required: "🎬", approval_required: "✅", offer: "🎉",
  };
  return (
    <div style={{ position: "relative" }} ref={ref}>
      <button onClick={() => { setOpen(!open); load(); }} aria-label="Notifications">
        🔔 {data.unread > 0 && <span className="badge critical">{data.unread}</span>}
      </button>
      {open && (
        <div className="notif-panel">
          <div className="row" style={{ justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--border)" }}>
            <b>Notifications</b>
            <button className="sm" onClick={() => api.post("/notifications/read-all").then(load)}>Mark all read</button>
          </div>
          {!data.items.length && <div className="empty">No notifications yet</div>}
          {data.items.map((n) => (
            <div key={n.id} className={`notif ${n.is_read ? "" : "unread"}`}
              onClick={() => { api.post(`/notifications/${n.id}/read`).then(load); if (n.link) nav(n.link); setOpen(false); }}>
              <div><span style={{ marginRight: 6 }}>{icon[n.type] || "•"}</span><b>{n.title}</b></div>
              {n.message && <div className="small secondary">{n.message}</div>}
              <div className="small muted">{fmtDateTime(n.created_at)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TopBar() {
  const run = useAction();
  const [ai, setAi] = useState<any>(null);
  useEffect(() => { api.get("/settings/ai-status").then(setAi).catch(() => {}); }, []);
  return (
    <div className="topbar">
      <div className="small muted">
        {ai && (ai.available ? <>AI: <b className="secondary">{ai.active}</b> · {ai.model}</> : <>AI: templates only (add an API key in .env)</>)}
      </div>
      <div className="row">
        <button onClick={() => run(() => api.post("/automation/run"), "Job hunt started — new jobs will appear shortly")}>▶ Run job hunt</button>
        <Notifications />
      </div>
    </div>
  );
}

export default function App() {
  const [counts, setCounts] = useState<{ approvals: number; followups: number }>({ approvals: 0, followups: 0 });
  useEffect(() => {
    const load = () =>
      api.get("/dashboard").then((d) => setCounts({ approvals: d.pending_approvals, followups: d.due_follow_ups.length })).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">🎯 AI Job Hunter</div>
        <nav className="nav">
          {NAV.map((n, i) =>
            n ? (
              <NavLink key={n[0]} to={n[0]} end={n[0] === "/"}>
                <span>{n[2]} &nbsp;{n[1]}</span>
                {n[0] === "/approvals" && counts.approvals > 0 && <span className="badge warning">{counts.approvals}</span>}
                {n[0] === "/followups" && counts.followups > 0 && <span className="badge accent">{counts.followups}</span>}
              </NavLink>
            ) : (
              <div key={i} className="sep" />
            ),
          )}
        </nav>
      </aside>
      <div className="main">
        <TopBar />
        <div className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/queue" element={<ApplyQueue />} />
            <Route path="/applications" element={<Applications />} />
            <Route path="/applications/:id" element={<ApplicationDetail />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/contacts" element={<Contacts />} />
            <Route path="/contacts/:id" element={<ContactDetail />} />
            <Route path="/interviews" element={<Interviews />} />
            <Route path="/followups" element={<FollowUps />} />
            <Route path="/resumes" element={<Resumes />} />
            <Route path="/videos" element={<Videos />} />
            <Route path="/answers" element={<Answers />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<div className="empty">Page not found</div>} />
          </Routes>
        </div>
      </div>
    </div>
  );
}

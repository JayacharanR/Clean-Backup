import { useState, useEffect } from "react";

const API_BASE = "";

export default function WatcherSettings() {
  const [watchers, setWatchers] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Form state
  const [label, setLabel] = useState("");
  const [watchPath, setWatchPath] = useState("");
  const [pipelineStep, setPipelineStep] = useState("classify");
  const [pipeline, setPipeline] = useState([]);

  useEffect(() => { fetchWatchers(); }, []);

  const fetchWatchers = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/watchers`);
      if (!res.ok) throw new Error("fetch failed");
      const data = await res.json();
      setWatchers(data.watchers || []);
      setEvents(data.events || []);
    } catch {
      setError("Failed to fetch watchers.");
    } finally {
      setLoading(false);
    }
  };

  const handleAddWatcher = async (e) => {
    e.preventDefault();
    if (!watchPath.trim()) return alert("Watch path is required");
    try {
      const res = await fetch(`${API_BASE}/api/watchers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: label || "New Watcher",
          watch_path: watchPath,
          pipeline,
          enabled: true,
          recursive: true,
          stability_window_seconds: 3,
        }),
      });
      if (!res.ok) throw new Error("create failed");
      setLabel(""); setWatchPath(""); setPipeline([]);
      fetchWatchers();
    } catch (err) {
      alert(err.message || "Failed to create watcher");
    }
  };

  const addPipelineStep = () => {
    setPipeline([...pipeline, { job_type: pipelineStep, enabled: true }]);
  };

  const removePipelineStep = (idx) => {
    setPipeline(pipeline.filter((_, i) => i !== idx));
  };

  const toggleWatcher = async (id, currentEnabled) => {
    try {
      await fetch(`${API_BASE}/api/watchers/${id}/${currentEnabled ? "stop" : "start"}`, { method: "POST" });
      fetchWatchers();
    } catch { alert("Failed to toggle watcher"); }
  };

  const deleteWatcher = async (id) => {
    if (!window.confirm("Delete this watcher?")) return;
    try {
      await fetch(`${API_BASE}/api/watchers/${id}`, { method: "DELETE" });
      fetchWatchers();
    } catch { alert("Failed to delete watcher"); }
  };

  const STEP_LABELS = {
    classify: "Classify",
    "organize-by-date": "Organize by Date",
    dedupe: "Deduplicate",
    cloud_sync: "Cloud Sync",
  };

  if (loading) return <section className="panel" style={{ textAlign: "center", color: "var(--muted)" }}>Loading watchers…</section>;

  return (
    <>
      <section className="panel">
        <h2>Watcher Daemon</h2>
        <p style={{ color: "var(--muted)", marginBottom: 16 }}>
          Automatically run pipelines when new files are dropped into specific folders.
        </p>

        {error && <div style={{ background: "#fef2f2", color: "var(--accent-2)", padding: 12, borderRadius: 10, marginBottom: 12 }}>{error}</div>}

        <div className="watcher-grid">
          {/* ── Left: Create form ───────────────────────────── */}
          <div className="watcher-form-card">
            <h3 style={{ margin: "0 0 14px" }}>Create Watcher</h3>
            <form onSubmit={handleAddWatcher}>
              <label>
                Label
                <input type="text" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g., SD Card Drop" />
              </label>

              <label>
                Watch Folder Path *
                <input type="text" value={watchPath} onChange={(e) => setWatchPath(e.target.value)} placeholder="/path/to/watch" required />
              </label>

              <label>Pipeline Steps</label>
              <div className="pipeline-add-row">
                <select value={pipelineStep} onChange={(e) => setPipelineStep(e.target.value)}>
                  <option value="classify">Classify</option>
                  <option value="organize-by-date">Organize by Date</option>
                  <option value="dedupe">Deduplicate</option>
                  <option value="cloud_sync">Cloud Sync</option>
                </select>
                <button type="button" className="secondary" onClick={addPipelineStep}>+ Add</button>
              </div>

              {pipeline.length > 0 ? (
                <ul className="pipeline-list">
                  {pipeline.map((step, idx) => (
                    <li key={idx} className="pipeline-item">
                      <span className="pipeline-step-num">{idx + 1}.</span>
                      <span className="pipeline-step-label">{STEP_LABELS[step.job_type] || step.job_type}</span>
                      <button type="button" className="danger small" onClick={() => removePipelineStep(idx)}>✕</button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p style={{ color: "var(--muted)", fontStyle: "italic", fontSize: "0.88rem" }}>No steps added yet.</p>
              )}

              <button type="submit" className="primary" disabled={pipeline.length === 0} style={{ width: "100%", marginTop: 12 }}>
                Create Watcher
              </button>
            </form>
          </div>

          {/* ── Right: Active watchers + events ─────────────── */}
          <div className="watcher-right-col">
            <div className="watcher-list-card">
              <h3 style={{ margin: "0 0 14px" }}>Active Watchers</h3>
              {watchers.length === 0 ? (
                <p style={{ color: "var(--muted)", textAlign: "center", padding: "24px 0" }}>No watchers configured.</p>
              ) : (
                <div className="watcher-list">
                  {watchers.map((w) => (
                    <div key={w.id} className="watcher-card">
                      <div className="watcher-card-head">
                        <div>
                          <strong>{w.label}</strong>
                          <div className="watcher-path" title={w.watch_path}>{w.watch_path}</div>
                        </div>
                        <div className="watcher-actions">
                          <button className={w.enabled ? "watcher-badge active" : "watcher-badge"} onClick={() => toggleWatcher(w.id, w.enabled)}>
                            {w.enabled ? "Active" : "Paused"}
                          </button>
                          <button className="danger small" onClick={() => deleteWatcher(w.id)}>Delete</button>
                        </div>
                      </div>
                      <div className="watcher-pipeline-tags">
                        {w.pipeline.map((step, idx) => (
                          <span key={idx} className="pipeline-tag">{STEP_LABELS[step.job_type] || step.job_type}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="watcher-list-card" style={{ marginTop: 16 }}>
              <h3 style={{ margin: "0 0 14px" }}>Recent Events</h3>
              {events.length === 0 ? (
                <p style={{ color: "var(--muted)", textAlign: "center", padding: "24px 0" }}>No recent activity.</p>
              ) : (
                <div className="event-feed">
                  {events.map((ev) => (
                    <div key={ev.id} className="event-row">
                      <div className="event-row-head">
                        <span>{ev.watcher_label || "—"}</span>
                        <span className={`event-status ${ev.status === "completed" ? "ok" : ev.status === "failed" ? "err" : ""}`}>
                          {ev.status}
                        </span>
                      </div>
                      <div className="event-row-file" title={ev.file_path}>{ev.file_path.split("/").pop()}</div>
                      <div className="event-row-time">{new Date(ev.detected_at).toLocaleString()}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

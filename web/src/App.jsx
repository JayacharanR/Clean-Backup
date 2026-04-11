import { useEffect, useMemo, useState } from "react";

const API_BASE = "";

function imageUrl(path, variant = "thumb") {
  return `${API_BASE}/api/image?path=${encodeURIComponent(path)}&variant=${variant}`;
}

function bytesToHuman(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / (1024 ** 3)).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / (1024 ** 2)).toFixed(2)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${bytes} B`;
}

function JobProgress({ title, job }) {
  if (!job) return null;
  return (
    <div className="progress-wrap">
      <div className="progress-label">
        <span>{title}: {job.message}</span>
        <span>{job.progress}%</span>
      </div>
      <div className="progress-bar">
        <div style={{ width: `${job.progress}%` }} />
      </div>
    </div>
  );
}

function PreviewModal({ group, index, onClose, onPrev, onNext }) {
  if (!group || index < 0 || index >= group.images.length) return null;
  const item = group.images[index];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-shell" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>Close</button>

        <button className="nav-arrow left" onClick={onPrev} aria-label="Previous image">
          {"<"}
        </button>

        <img className="modal-image" src={imageUrl(item.path, "full")} alt={item.name} />

        <button className="nav-arrow right" onClick={onNext} aria-label="Next image">
          {">"}
        </button>

        <div className="modal-meta">
          <div>{item.name}</div>
          <div>{item.width || "?"}x{item.height || "?"} | {item.size_human}</div>
          {item.is_best ? <span className="best-tag">Best Image</span> : null}
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("duplicates");
  const [error, setError] = useState("");

  const [configThreshold, setConfigThreshold] = useState(5);
  const [configSaving, setConfigSaving] = useState(false);
  const [configMessage, setConfigMessage] = useState("");

  const [sessions, setSessions] = useState([]);
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoFilter, setUndoFilter] = useState("");

  const [sourceDir, setSourceDir] = useState("");
  const [threshold, setThreshold] = useState(5);
  const [dupJobId, setDupJobId] = useState(null);
  const [dupJob, setDupJob] = useState(null);
  const [groups, setGroups] = useState([]);
  const [scanSummary, setScanSummary] = useState(null);
  const [selected, setSelected] = useState({});
  const [deleteMode, setDeleteMode] = useState("trash");
  const [allowBestDelete, setAllowBestDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);

  const [previewGroupIndex, setPreviewGroupIndex] = useState(-1);
  const [previewImageIndex, setPreviewImageIndex] = useState(-1);

  const [orgSource, setOrgSource] = useState("");
  const [orgDestination, setOrgDestination] = useState("");
  const [orgOperation, setOrgOperation] = useState("move");
  const [orgCheckDuplicates, setOrgCheckDuplicates] = useState(false);
  const [orgCheckNameDuplicates, setOrgCheckNameDuplicates] = useState(false);
  const [orgThreshold, setOrgThreshold] = useState(5);
  const [orgJobId, setOrgJobId] = useState(null);
  const [orgJob, setOrgJob] = useState(null);
  const [orgResult, setOrgResult] = useState(null);

  const [cmpSource, setCmpSource] = useState("");
  const [cmpOutput, setCmpOutput] = useState("");
  const [cmpTypes, setCmpTypes] = useState("both");
  const [cmpLevel, setCmpLevel] = useState(2);
  const [cmpJobId, setCmpJobId] = useState(null);
  const [cmpJob, setCmpJob] = useState(null);
  const [cmpResult, setCmpResult] = useState(null);
  const [pickerBusyKey, setPickerBusyKey] = useState("");

  useEffect(() => {
    fetchConfig();
    fetchSessions();
  }, []);

  useEffect(() => {
    let timer = null;
    async function poll() {
      if (!dupJobId) return;
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${dupJobId}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Duplicate scan polling failed");

        setDupJob(data.job);
        if (data.job.status === "completed") {
          const result = data.job.result || {};
          setGroups(result.groups || []);
          setScanSummary(result);
          setSelected({});
          setDupJobId(null);
        } else if (data.job.status === "failed") {
          setError(data.job.error || "Duplicate scan failed");
          setDupJobId(null);
        } else {
          timer = window.setTimeout(poll, 1200);
        }
      } catch (err) {
        setError(err.message || "Duplicate scan polling failed");
        setDupJobId(null);
      }
    }

    if (dupJobId) poll();
    return () => {
      if (timer) window.clearTimeout(timer);
    };
  }, [dupJobId]);

  useEffect(() => {
    let timer = null;
    async function poll() {
      if (!orgJobId) return;
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${orgJobId}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Organize job polling failed");

        setOrgJob(data.job);
        if (data.job.status === "completed") {
          setOrgResult(data.job.result || null);
          setOrgJobId(null);
          fetchSessions();
        } else if (data.job.status === "failed") {
          setError(data.job.error || "Organize job failed");
          setOrgJobId(null);
        } else {
          timer = window.setTimeout(poll, 1200);
        }
      } catch (err) {
        setError(err.message || "Organize job polling failed");
        setOrgJobId(null);
      }
    }

    if (orgJobId) poll();
    return () => {
      if (timer) window.clearTimeout(timer);
    };
  }, [orgJobId]);

  useEffect(() => {
    let timer = null;
    async function poll() {
      if (!cmpJobId) return;
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${cmpJobId}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Compression job polling failed");

        setCmpJob(data.job);
        if (data.job.status === "completed") {
          setCmpResult(data.job.result || null);
          setCmpJobId(null);
        } else if (data.job.status === "failed") {
          setError(data.job.error || "Compression job failed");
          setCmpJobId(null);
        } else {
          timer = window.setTimeout(poll, 1200);
        }
      } catch (err) {
        setError(err.message || "Compression job polling failed");
        setCmpJobId(null);
      }
    }

    if (cmpJobId) poll();
    return () => {
      if (timer) window.clearTimeout(timer);
    };
  }, [cmpJobId]);

  useEffect(() => {
    function onKeyDown(event) {
      if (previewGroupIndex < 0) return;
      if (event.key === "Escape") closePreview();
      if (event.key === "ArrowLeft") movePreview(-1);
      if (event.key === "ArrowRight") movePreview(1);
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewGroupIndex, previewImageIndex, groups]);

  async function fetchConfig() {
    try {
      const res = await fetch(`${API_BASE}/api/config`);
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Could not load config");
      const nextThreshold = data.config?.phash_threshold ?? 5;
      setConfigThreshold(nextThreshold);
      setThreshold(nextThreshold);
      setOrgThreshold(nextThreshold);
    } catch (err) {
      setError(err.message || "Could not load config");
    }
  }

  async function saveConfigThreshold(e) {
    e.preventDefault();
    setConfigMessage("");
    setConfigSaving(true);
    setError("");

    try {
      const res = await fetch(`${API_BASE}/api/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phash_threshold: Number(configThreshold) })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Could not save config");

      const nextThreshold = data.config?.phash_threshold ?? configThreshold;
      setConfigThreshold(nextThreshold);
      setThreshold(nextThreshold);
      setOrgThreshold(nextThreshold);
      setConfigMessage("Saved successfully");
    } catch (err) {
      setError(err.message || "Could not save config");
    } finally {
      setConfigSaving(false);
    }
  }

  async function fetchSessions() {
    try {
      const res = await fetch(`${API_BASE}/api/undo/sessions`);
      const data = await res.json();
      if (data.ok) setSessions(data.sessions || []);
    } catch {
      // Keep non-blocking.
    }
  }

  async function pickFolder(fieldKey, currentValue, setPath) {
    if (pickerBusyKey) return;

    setPickerBusyKey(fieldKey);
    setError("");

    try {
      const res = await fetch(`${API_BASE}/api/folder/pick`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initial_dir: currentValue?.trim?.() || "" })
      });

      const contentType = (res.headers.get("content-type") || "").toLowerCase();
      if (!contentType.includes("application/json")) {
        const raw = await res.text();
        const looksLikeHtml = raw.trim().startsWith("<");
        if (looksLikeHtml || res.status === 404) {
          throw new Error("Folder picker API is unavailable. Restart the Python app and open Mode 6 again.");
        }
        throw new Error("Folder picker returned an unexpected response from server.");
      }

      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "Could not open folder picker");
      if (!data.cancelled && data.path) {
        setPath(data.path);
      }
    } catch (err) {
      setError(err.message || "Could not open folder picker");
    } finally {
      setPickerBusyKey("");
    }
  }

  async function startDuplicateScan(e) {
    e.preventDefault();
    setError("");
    if (!sourceDir.trim()) {
      setError("Source folder path is required");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/duplicates/scan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_dir: sourceDir.trim(),
          threshold: Number(threshold) || 5
        })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to start duplicate scan");
      setDupJobId(data.job_id);
      setScanSummary(null);
      setGroups([]);
    } catch (err) {
      setError(err.message || "Failed to start duplicate scan");
    }
  }

  function toggleSelect(image) {
    const locked = image.is_best && !allowBestDelete;
    if (locked) return;

    setSelected((prev) => {
      const next = { ...prev };
      if (next[image.path]) {
        delete next[image.path];
      } else {
        next[image.path] = image;
      }
      return next;
    });
  }

  function selectAllInGroup(group) {
    setSelected((prev) => {
      const next = { ...prev };
      for (const image of group.images) {
        if (image.is_best && !allowBestDelete) continue;
        next[image.path] = image;
      }
      return next;
    });
  }

  function clearGroupSelection(group) {
    setSelected((prev) => {
      const next = { ...prev };
      for (const image of group.images) delete next[image.path];
      return next;
    });
  }

  const selectedList = useMemo(() => Object.values(selected), [selected]);
  const selectedCount = selectedList.length;
  const selectedBytes = useMemo(() => selectedList.reduce((sum, item) => sum + (item.size_bytes || 0), 0), [selectedList]);

  async function deleteSelected() {
    if (selectedCount === 0) {
      setError("No images selected");
      return;
    }

    if (deleteMode === "permanent" && confirmText !== "DELETE") {
      setError("Type DELETE to confirm permanent delete");
      return;
    }

    setDeleteBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/duplicates/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          selected_images: selectedList,
          mode: deleteMode,
          allow_best_delete: allowBestDelete,
          confirm_text: confirmText
        })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Delete action failed");

      const deletedSet = new Set(data.deleted_paths || []);
      const nextGroups = groups
        .map((group) => ({ ...group, images: group.images.filter((image) => !deletedSet.has(image.path)) }))
        .filter((group) => group.images.length > 1);

      setGroups(nextGroups);
      setSelected({});
      setConfirmText("");
      setScanSummary((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          duplicate_groups: nextGroups.length,
          total_duplicates: Math.max(0, (prev.total_duplicates || 0) - (data.deleted_count || 0))
        };
      });
      fetchSessions();
    } catch (err) {
      setError(err.message || "Delete action failed");
    } finally {
      setDeleteBusy(false);
    }
  }

  async function startOrganize(e) {
    e.preventDefault();
    setError("");

    if (!orgSource.trim() || !orgDestination.trim()) {
      setError("Source and destination are required for organize");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/organize/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_dir: orgSource.trim(),
          destination_dir: orgDestination.trim(),
          operation: orgOperation,
          check_duplicates: orgCheckDuplicates,
          duplicate_threshold: Number(orgThreshold) || 5,
          check_name_duplicates: orgCheckNameDuplicates
        })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to start organize task");
      setOrgResult(null);
      setOrgJobId(data.job_id);
    } catch (err) {
      setError(err.message || "Failed to start organize task");
    }
  }

  async function startCompression(e) {
    e.preventDefault();
    setError("");

    if (!cmpSource.trim() || !cmpOutput.trim()) {
      setError("Source and output are required for compression");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/compress/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_dir: cmpSource.trim(),
          output_dir: cmpOutput.trim(),
          level: Number(cmpLevel) || 2,
          file_types: cmpTypes
        })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to start compression task");
      setCmpResult(null);
      setCmpJobId(data.job_id);
    } catch (err) {
      setError(err.message || "Failed to start compression task");
    }
  }

  async function revertSession(sessionId) {
    setUndoBusy(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/undo/revert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId })
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Undo failed");
      fetchSessions();
    } catch (err) {
      setError(err.message || "Undo failed");
    } finally {
      setUndoBusy(false);
    }
  }

  function exportUndoSessions() {
    const payload = {
      exported_at: new Date().toISOString(),
      total: filteredSessions.length,
      sessions: filteredSessions
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "clean-backup-undo-sessions.json";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function openPreview(groupIndex, imageIndex) {
    setPreviewGroupIndex(groupIndex);
    setPreviewImageIndex(imageIndex);
  }

  function closePreview() {
    setPreviewGroupIndex(-1);
    setPreviewImageIndex(-1);
  }

  function movePreview(step) {
    const group = groups[previewGroupIndex];
    if (!group) return;
    const count = group.images.length;
    const next = (previewImageIndex + step + count) % count;
    setPreviewImageIndex(next);
  }

  const previewGroup = previewGroupIndex >= 0 ? groups[previewGroupIndex] : null;
  const filteredSessions = useMemo(() => {
    const q = undoFilter.trim().toLowerCase();
    if (!q) return sessions;
    return sessions.filter((session) => {
      return session.id.toLowerCase().includes(q) || String(session.count).includes(q);
    });
  }, [sessions, undoFilter]);

  return (
    <div className="page-shell">
      <div className="orb orb-a" />
      <div className="orb orb-b" />

      <header className="hero">
        <h1>Clean-Backup Web Studio</h1>
        <p>
          Phase 2 is active: duplicates, organize, sensitivity settings, undo history picker, and compression all run in one local GUI.
        </p>
      </header>

      <section className="panel tab-panel">
        <div className="tab-row">
          <button className={`tab-btn ${activeTab === "duplicates" ? "active" : ""}`} onClick={() => setActiveTab("duplicates")}>Duplicates</button>
          <button className={`tab-btn ${activeTab === "organize" ? "active" : ""}`} onClick={() => setActiveTab("organize")}>Organize</button>
          <button className={`tab-btn ${activeTab === "compression" ? "active" : ""}`} onClick={() => setActiveTab("compression")}>Compression</button>
          <button className={`tab-btn ${activeTab === "settings" ? "active" : ""}`} onClick={() => setActiveTab("settings")}>Sensitivity</button>
          <button className={`tab-btn ${activeTab === "undo" ? "active" : ""}`} onClick={() => setActiveTab("undo")}>Undo History</button>
        </div>
      </section>

      {error ? <div className="error-box">{error}</div> : null}

      {activeTab === "duplicates" ? (
        <>
          <section className="panel scan-panel">
            <form onSubmit={startDuplicateScan} className="scan-form">
              <label>
                Source folder path
                <div className="path-input-row">
                  <input type="text" value={sourceDir} onChange={(e) => setSourceDir(e.target.value)} placeholder="/absolute/path/to/folder" />
                  <button
                    type="button"
                    className="secondary browse-btn"
                    onClick={() => pickFolder("dup_source", sourceDir, setSourceDir)}
                    disabled={Boolean(dupJobId) || Boolean(pickerBusyKey)}
                  >
                    {pickerBusyKey === "dup_source" ? "Opening..." : "Select Folder"}
                  </button>
                </div>
              </label>

              <label>
                Sensitivity threshold
                <input type="number" min="0" max="25" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
              </label>

              <button className="primary" type="submit" disabled={Boolean(dupJobId)}>
                {dupJobId ? "Scanning..." : "Scan for Duplicates"}
              </button>
            </form>

            <JobProgress title="Duplicate scan" job={dupJob} />

            {scanSummary ? (
              <div className="summary-grid">
                <div><span>Groups</span><strong>{scanSummary.duplicate_groups}</strong></div>
                <div><span>Duplicates</span><strong>{scanSummary.total_duplicates}</strong></div>
                <div><span>Recoverable</span><strong>{scanSummary.space_recoverable_human}</strong></div>
                <div><span>Backend</span><strong>{scanSummary.backend}</strong></div>
              </div>
            ) : null}
          </section>

          <section className="panel action-panel">
            <h2>Bulk Actions</h2>
            <p>Selected: <strong>{selectedCount}</strong> images | Estimated reclaim: <strong>{bytesToHuman(selectedBytes)}</strong></p>

            <div className="action-controls">
              <label>
                Delete mode
                <select value={deleteMode} onChange={(e) => setDeleteMode(e.target.value)}>
                  <option value="trash">Move to Trash (undo-friendly)</option>
                  <option value="permanent">Permanent delete</option>
                </select>
              </label>

              <label className="checkbox-row">
                <input type="checkbox" checked={allowBestDelete} onChange={(e) => setAllowBestDelete(e.target.checked)} />
                Allow deleting best images
              </label>

              {deleteMode === "permanent" ? (
                <label>
                  Type DELETE to confirm
                  <input type="text" value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="DELETE" />
                </label>
              ) : null}
            </div>

            <div className="action-buttons">
              <button className="danger" onClick={deleteSelected} disabled={deleteBusy || selectedCount === 0}>Delete Selected</button>
            </div>
          </section>

          <section className="groups-wrap">
            {groups.length === 0 ? (
              <div className="empty-state">No duplicate groups yet. Start a scan to populate this view.</div>
            ) : groups.map((group, groupIndex) => (
              <article key={group.id} className="group-card">
                <div className="group-head">
                  <div>
                    <h3>Group {groupIndex + 1}</h3>
                    <p>{group.count} images | hash {group.hash}</p>
                  </div>
                  <div className="group-head-actions">
                    <button onClick={() => selectAllInGroup(group)}>Select group</button>
                    <button onClick={() => clearGroupSelection(group)}>Clear group</button>
                  </div>
                </div>

                <div className="group-grid">
                  {group.images.map((image, imageIndex) => {
                    const locked = image.is_best && !allowBestDelete;
                    const checked = Boolean(selected[image.path]);
                    return (
                      <div key={image.path} className={`image-card ${image.is_best ? "best" : ""}`}>
                        <img src={imageUrl(image.path, "thumb")} alt={image.name} onClick={() => openPreview(groupIndex, imageIndex)} />
                        <div className="meta">
                          <div className="name-row">
                            <strong title={image.name}>{image.name}</strong>
                            {image.is_best ? <span className="best-tag">Best</span> : null}
                          </div>
                          <div className="subtle">{image.width || "?"}x{image.height || "?"} | {image.size_human}</div>
                        </div>
                        <label className={`select-row ${locked ? "locked" : ""}`}>
                          <input type="checkbox" checked={checked} disabled={locked} onChange={() => toggleSelect(image)} />
                          {locked ? "Protected best image" : "Select for deletion"}
                        </label>
                      </div>
                    );
                  })}
                </div>
              </article>
            ))}
          </section>
        </>
      ) : null}

      {activeTab === "organize" ? (
        <section className="panel">
          <h2>Organize Files by Date</h2>
          <form onSubmit={startOrganize} className="grid-two">
            <label>
              Source directory
              <div className="path-input-row">
                <input type="text" value={orgSource} onChange={(e) => setOrgSource(e.target.value)} placeholder="/path/source" />
                <button
                  type="button"
                  className="secondary browse-btn"
                  onClick={() => pickFolder("org_source", orgSource, setOrgSource)}
                  disabled={Boolean(orgJobId) || Boolean(pickerBusyKey)}
                >
                  {pickerBusyKey === "org_source" ? "Opening..." : "Select Folder"}
                </button>
              </div>
            </label>
            <label>
              Destination directory
              <div className="path-input-row">
                <input type="text" value={orgDestination} onChange={(e) => setOrgDestination(e.target.value)} placeholder="/path/destination" />
                <button
                  type="button"
                  className="secondary browse-btn"
                  onClick={() => pickFolder("org_destination", orgDestination, setOrgDestination)}
                  disabled={Boolean(orgJobId) || Boolean(pickerBusyKey)}
                >
                  {pickerBusyKey === "org_destination" ? "Opening..." : "Select Folder"}
                </button>
              </div>
            </label>
            <label>
              Operation
              <select value={orgOperation} onChange={(e) => setOrgOperation(e.target.value)}>
                <option value="move">Move</option>
                <option value="copy">Copy</option>
              </select>
            </label>
            <label>
              Duplicate threshold
              <input type="number" min="0" max="25" value={orgThreshold} onChange={(e) => setOrgThreshold(e.target.value)} />
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={orgCheckDuplicates} onChange={(e) => setOrgCheckDuplicates(e.target.checked)} />
              Check perceptual duplicates
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={orgCheckNameDuplicates} onChange={(e) => setOrgCheckNameDuplicates(e.target.checked)} />
              Check name-based duplicates
            </label>
            <button className="primary" type="submit" disabled={Boolean(orgJobId)}>Start Organize Job</button>
          </form>

          <JobProgress title="Organize" job={orgJob} />

          {orgResult ? (
            <div className="result-panel">
              <h3>Organize Summary</h3>
              <div className="kv-grid">
                <div><span>Processed</span><strong>{orgResult.stats.processed}</strong></div>
                <div><span>Errors</span><strong>{orgResult.stats.errors}</strong></div>
                <div><span>Images</span><strong>{orgResult.stats.images}</strong></div>
                <div><span>Videos</span><strong>{orgResult.stats.videos}</strong></div>
                <div><span>Perceptual duplicates</span><strong>{orgResult.stats.perceptual_duplicates}</strong></div>
                <div><span>Name duplicates</span><strong>{orgResult.stats.name_duplicates}</strong></div>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeTab === "compression" ? (
        <section className="panel">
          <h2>Compress Images and Videos</h2>
          <form onSubmit={startCompression} className="grid-two">
            <label>
              Source directory
              <div className="path-input-row">
                <input type="text" value={cmpSource} onChange={(e) => setCmpSource(e.target.value)} placeholder="/path/source" />
                <button
                  type="button"
                  className="secondary browse-btn"
                  onClick={() => pickFolder("cmp_source", cmpSource, setCmpSource)}
                  disabled={Boolean(cmpJobId) || Boolean(pickerBusyKey)}
                >
                  {pickerBusyKey === "cmp_source" ? "Opening..." : "Select Folder"}
                </button>
              </div>
            </label>
            <label>
              Output directory
              <div className="path-input-row">
                <input type="text" value={cmpOutput} onChange={(e) => setCmpOutput(e.target.value)} placeholder="/path/output" />
                <button
                  type="button"
                  className="secondary browse-btn"
                  onClick={() => pickFolder("cmp_output", cmpOutput, setCmpOutput)}
                  disabled={Boolean(cmpJobId) || Boolean(pickerBusyKey)}
                >
                  {pickerBusyKey === "cmp_output" ? "Opening..." : "Select Folder"}
                </button>
              </div>
            </label>
            <label>
              File types
              <select value={cmpTypes} onChange={(e) => setCmpTypes(e.target.value)}>
                <option value="images">Images only</option>
                <option value="videos">Videos only</option>
                <option value="both">Images and videos</option>
              </select>
            </label>
            <label>
              Compression level
              <select value={cmpLevel} onChange={(e) => setCmpLevel(Number(e.target.value))}>
                <option value={1}>1 - High quality</option>
                <option value={2}>2 - Balanced</option>
                <option value={3}>3 - Maximum compression</option>
              </select>
            </label>
            <button className="primary" type="submit" disabled={Boolean(cmpJobId)}>Start Compression Job</button>
          </form>

          <JobProgress title="Compression" job={cmpJob} />

          {cmpResult ? (
            <div className="result-panel">
              <h3>Compression Summary</h3>
              <div className="kv-grid">
                <div><span>Total files</span><strong>{cmpResult.stats.total_files}</strong></div>
                <div><span>Images</span><strong>{cmpResult.stats.images_compressed}</strong></div>
                <div><span>Videos</span><strong>{cmpResult.stats.videos_compressed}</strong></div>
                <div><span>Errors</span><strong>{cmpResult.stats.errors}</strong></div>
                <div><span>Space saved</span><strong>{bytesToHuman(cmpResult.stats.space_saved)}</strong></div>
                <div><span>Ratio</span><strong>{Number(cmpResult.stats.compression_ratio || 0).toFixed(2)}%</strong></div>
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeTab === "settings" ? (
        <section className="panel">
          <h2>Duplicate Sensitivity Configuration</h2>
          <form onSubmit={saveConfigThreshold} className="settings-form">
            <label>
              Active pHash threshold
              <input type="number" min="0" max="25" value={configThreshold} onChange={(e) => setConfigThreshold(e.target.value)} />
            </label>
            <button className="primary" type="submit" disabled={configSaving}>Save Threshold</button>
          </form>
          {configMessage ? <div className="ok-box">{configMessage}</div> : null}
          <p className="subtle">Lower values are stricter; higher values catch more near-duplicates.</p>
        </section>
      ) : null}

      {activeTab === "undo" ? (
        <section className="panel">
          <div className="section-head">
            <h2>Undo History</h2>
            <div className="undo-toolbar">
              <input
                type="text"
                value={undoFilter}
                onChange={(e) => setUndoFilter(e.target.value)}
                placeholder="Filter by session id or count"
              />
              <button onClick={fetchSessions}>Refresh Sessions</button>
              <button onClick={exportUndoSessions} disabled={filteredSessions.length === 0}>Export JSON</button>
            </div>
          </div>

          {filteredSessions.length === 0 ? (
            <div className="empty-state">No undo sessions available.</div>
          ) : (
            <div className="session-list">
              {filteredSessions.map((session) => (
                <div key={session.id} className="session-row">
                  <div>
                    <div className="session-id">{session.id}</div>
                    <div className="subtle">{session.count} actions</div>
                  </div>
                  <button className="danger" onClick={() => revertSession(session.id)} disabled={undoBusy}>Revert this session</button>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}

      <PreviewModal
        group={previewGroup}
        index={previewImageIndex}
        onClose={closePreview}
        onPrev={() => movePreview(-1)}
        onNext={() => movePreview(1)}
      />
    </div>
  );
}

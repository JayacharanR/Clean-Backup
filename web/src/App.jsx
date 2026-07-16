import { useEffect, useMemo, useState } from "react";
import WatcherSettings from "./components/WatcherSettings";

const API_BASE = "";

const CATEGORY_ICONS = {
  videos: "🎥", documents: "📄", screenshots: "🖥️", people: "👤",
  travel: "✈️", family: "👨‍👩‍👧‍👦", selfies: "🤳", events: "🎉",
  nature: "🌿", food: "🍽️", pets: "🐾", vehicles: "🚗",
  art: "🏛️", night: "🌙", other: "📁",
};

const STAGE_NAMES = ["EXIF", "Heuristic", "Scene", "Faces", "Recognition", "Resolve"];

function imageUrl(path, variant = "thumb") {
  return `${API_BASE}/api/image?path=${encodeURIComponent(path)}&variant=${variant}`;
}

function bytesToHuman(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / (1024 ** 3)).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / (1024 ** 2)).toFixed(2)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(2)} KB`;
  return `${bytes} B`;
}

function formatSeconds(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0.00s";
  return `${n.toFixed(2)}s`;
}

function formatPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0.0%";
  return `${n.toFixed(1)}%`;
}

function normalizeProgress(value) {
  const parsed = typeof value === "number" ? value : parseFloat(String(value).replace("%", ""));
  if (Number.isNaN(parsed)) return 0;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function JobProgress({ title, job }) {
  if (!job) return null;
  const safeProgress = normalizeProgress(job.progress);
  return (
    <div className="progress-wrap">
      <div className="progress-label">
        <span>{title}: {job.message}</span>
        <span>{safeProgress}%</span>
      </div>
      <div className="progress-bar">
        <div style={{ width: `${safeProgress}%` }} />
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

  // ── Classify state ──────────────────────────────────────────────────
  const [clsSource, setClsSource] = useState("");
  const [clsCategories, setClsCategories] = useState([]);
  const [clsFolderScheme, setClsFolderScheme] = useState("yyyy_mm_category");
  const [clsMultiCategory, setClsMultiCategory] = useState("tags");
  const [clsFaceSensitivity, setClsFaceSensitivity] = useState("balanced");
  const [clsConfidence, setClsConfidence] = useState(0.5);
  const [clsHomeLat, setClsHomeLat] = useState("");
  const [clsHomeLon, setClsHomeLon] = useState("");
  const [clsJobId, setClsJobId] = useState(null);
  const [clsJob, setClsJob] = useState(null);
  const [clsResult, setClsResult] = useState(null);
  const [clsRunId, setClsRunId] = useState(null);
  const [clsDest, setClsDest] = useState("");
  const [clsOperation, setClsOperation] = useState("move");
  const [clsApplyJobId, setClsApplyJobId] = useState(null);
  const [clsApplyJob, setClsApplyJob] = useState(null);
  // ── People state ────────────────────────────────────────────────────
  const [people, setPeople] = useState([]);
  const [faceClusters, setFaceClusters] = useState([]);
  const [newPersonName, setNewPersonName] = useState("");
  const [clusterNames, setClusterNames] = useState({});

  // ── Review queue state ──────────────────────────────────────────────
  const [reviewQueue, setReviewQueue] = useState([]);
  const [reviewFilter, setReviewFilter] = useState("all");

  // ── Settings: purge ─────────────────────────────────────────────────
  const [purgeConfirm, setPurgeConfirm] = useState("");
  const [purgeBusy, setPurgeBusy] = useState(false);

  // ── Cloud Sync state ────────────────────────────────────────────────
  const [cloudAccounts, setCloudAccounts] = useState([]);
  const [syncHistory, setSyncHistory] = useState([]);
  const [syncSource, setSyncSource] = useState("");
  const [syncRemotePath, setSyncRemotePath] = useState("Clean-Backup");
  const [syncFolderScheme, setSyncFolderScheme] = useState("mirror");
  const [syncType, setSyncType] = useState("incremental");
  const [syncDuplicateHandling, setSyncDuplicateHandling] = useState("skip");
  const [syncThrottleKb, setSyncThrottleKb] = useState("");
  const [syncSelectedAccount, setSyncSelectedAccount] = useState("");
  const [syncJobId, setSyncJobId] = useState(null);
  const [syncJob, setSyncJob] = useState(null);
  const [syncRunId, setSyncRunId] = useState(null);
  const [syncConnecting, setSyncConnecting] = useState(false);
  const [syncUndoJobId, setSyncUndoJobId] = useState(null);
  const [syncUndoJob, setSyncUndoJob] = useState(null);
  const [syncPromptVisible, setSyncPromptVisible] = useState(false);
  const [syncPromptDismissed, setSyncPromptDismissed] = useState(false);

  useEffect(() => {
    fetchConfig();
    fetchSessions();
    fetchCategories();
    fetchCloudAccounts();
  }, []);

  // ── Cloud Sync job polling ──────────────────────────────────────────
  useEffect(() => {
    let timer = null;
    async function poll() {
      if (!syncJobId) return;
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${syncJobId}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Sync job polling failed");

        setSyncJob(data.job);
        if (data.job.status === "completed") {
          setSyncJobId(null);
          fetchSyncHistory();
          fetchSessions();
        } else if (data.job.status === "failed") {
          setError(data.job.error || "Sync job failed");
          setSyncJobId(null);
        } else {
          timer = window.setTimeout(poll, 800);
        }
      } catch (err) {
        setError(err.message || "Sync job polling failed");
        setSyncJobId(null);
      }
    }
    if (syncJobId) poll();
    return () => { if (timer) window.clearTimeout(timer); };
  }, [syncJobId]);

  // ── Cloud Undo job polling ──────────────────────────────────────────
  useEffect(() => {
    let timer = null;
    async function poll() {
      if (!syncUndoJobId) return;
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${syncUndoJobId}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Undo job polling failed");

        setSyncUndoJob(data.job);
        if (data.job.status === "completed") {
          setSyncUndoJobId(null);
          fetchSyncHistory();
        } else if (data.job.status === "failed") {
          setError(data.job.error || "Undo job failed");
          setSyncUndoJobId(null);
        } else {
          timer = window.setTimeout(poll, 800);
        }
      } catch (err) {
        setError(err.message || "Undo job polling failed");
        setSyncUndoJobId(null);
      }
    }
    if (syncUndoJobId) poll();
    return () => { if (timer) window.clearTimeout(timer); };
  }, [syncUndoJobId]);

  // ── Classify job polling ────────────────────────────────────────────
  useEffect(() => {
    let timer = null;
    async function poll() {
      if (!clsJobId) return;
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${clsJobId}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Classify job polling failed");

        setClsJob(data.job);
        if (data.job.status === "completed") {
          setClsResult(data.job.result || null);
          setClsJobId(null);
          fetchSessions();
        } else if (data.job.status === "failed") {
          setError(data.job.error || "Classify job failed");
          setClsJobId(null);
        } else {
          timer = window.setTimeout(poll, 800);
        }
      } catch (err) {
        setError(err.message || "Classify job polling failed");
        setClsJobId(null);
      }
    }
    if (clsJobId) poll();
    return () => { if (timer) window.clearTimeout(timer); };
  }, [clsJobId]);

  // ── Classify apply job polling ─────────────────────────────────────────
  useEffect(() => {
    let timer = null;
    async function poll() {
      if (!clsApplyJobId) return;
      try {
        const res = await fetch(`${API_BASE}/api/jobs/${clsApplyJobId}`);
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Apply job polling failed");

        setClsApplyJob(data.job);
        if (data.job.status === "completed") {
          setClsApplyJobId(null);
          fetchSessions();
        } else if (data.job.status === "failed") {
          setError(data.job.error || "Apply job failed");
          setClsApplyJobId(null);
        } else {
          timer = window.setTimeout(poll, 800);
        }
      } catch (err) {
        setError(err.message || "Apply job polling failed");
        setClsApplyJobId(null);
      }
    }
    if (clsApplyJobId) poll();
    return () => { if (timer) window.clearTimeout(timer); };
  }, [clsApplyJobId]);

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
          timer = window.setTimeout(poll, 500);
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

  async function fetchCategories() {
    try {
      const res = await fetch(`${API_BASE}/api/categories`);
      const data = await res.json();
      if (data.ok) setClsCategories(data.categories || []);
    } catch { /* non-blocking */ }
  }

  async function fetchPeople() {
    try {
      const res = await fetch(`${API_BASE}/api/people`);
      const data = await res.json();
      if (data.ok) setPeople(data.people || []);
    } catch { /* non-blocking */ }
  }

  async function fetchFaceClusters() {
    try {
      const res = await fetch(`${API_BASE}/api/faces/unidentified?cluster=true`);
      const data = await res.json();
      if (data.ok) setFaceClusters(data.clusters || []);
    } catch { /* non-blocking */ }
  }

  async function fetchReviewQueue() {
    try {
      const filterParam = reviewFilter !== "all" ? `?type=${reviewFilter}` : "";
      const res = await fetch(`${API_BASE}/api/review-queue${filterParam}`);
      const data = await res.json();
      if (data.ok) setReviewQueue(data.items || []);
    } catch { /* non-blocking */ }
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

  function toggleGroupSelection(group) {
    setSelected((prev) => {
      const next = { ...prev };

      const selectableImages = group.images.filter((image) => !(image.is_best && !allowBestDelete));
      if (selectableImages.length === 0) return next;

      const allSelected = selectableImages.every((image) => Boolean(next[image.path]));
      for (const image of selectableImages) {
        if (allSelected) {
          delete next[image.path];
        } else {
          next[image.path] = image;
        }
      }

      return next;
    });
  }

  function isGroupFullySelected(group) {
    const selectableImages = group.images.filter((image) => !(image.is_best && !allowBestDelete));
    if (selectableImages.length === 0) return false;
    return selectableImages.every((image) => Boolean(selected[image.path]));
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

  // ── Classify functions ──────────────────────────────────────────────
  function toggleCategory(catId) {
    setClsCategories(prev => prev.map(c =>
      c.id === catId ? { ...c, default_enabled: c.default_enabled ? 0 : 1 } : c
    ));
  }

  async function startClassify(e) {
    e.preventDefault();
    setError("");
    if (!clsSource.trim()) { setError("Source folder is required"); return; }

    const enabledCats = clsCategories.filter(c => c.default_enabled).map(c => c.key);
    const wizardConfig = {
      enabled_categories: enabledCats,
      folder_scheme: clsFolderScheme,
      multi_category: clsMultiCategory,
      face_sensitivity: clsFaceSensitivity,
      confidence_threshold: Number(clsConfidence),
      home_gps_lat: clsHomeLat,
      home_gps_lon: clsHomeLon,
    };

    try {
      const cfgRes = await fetch(`${API_BASE}/api/classify/config`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(wizardConfig),
      });
      const cfgData = await cfgRes.json();
      if (!cfgData.ok) throw new Error(cfgData.error || "Config save failed");

      const runId = cfgData.run_id;
      setClsRunId(runId);

      const startRes = await fetch(`${API_BASE}/api/classify/start`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, source_dir: clsSource.trim() }),
      });
      const startData = await startRes.json();
      if (!startData.ok) throw new Error(startData.error || "Failed to start classify");

      setClsResult(null);
      setClsJobId(startData.job_id);
    } catch (err) {
      setError(err.message || "Failed to start classify");
    }
  }

  function getActiveStage(message) {
    if (!message) return null;
    const m = message.toLowerCase();
    if (m.includes("stage a") || m.includes("exif")) return "EXIF";
    if (m.includes("stage b") || m.includes("heuristic")) return "Heuristic";
    if (m.includes("stage c") || m.includes("scene")) return "Scene";
    if (m.includes("stage d") || m.includes("faces") || m.includes("face")) return "Faces";
    if (m.includes("stage e") || m.includes("recognition") || m.includes("recogni")) return "Recognition";
    if (m.includes("stage f") || m.includes("resolve")) return "Resolve";
    return null;
  }

  async function startApply(e) {
    e.preventDefault();
    setError("");
    if (!clsDest.trim()) { setError("Destination folder is required"); return; }
    if (!clsRunId) { setError("No active classification run to apply"); return; }

    try {
      const res = await fetch(`${API_BASE}/api/classify/apply`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: clsRunId,
          dest_dir: clsDest.trim(),
          operation: clsOperation
        }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to start apply");

      setClsApplyJobId(data.job_id);
    } catch (err) {
      setError(err.message || "Failed to start apply");
    }
  }

  // ── People functions ────────────────────────────────────────────────
  async function addPerson(e) {
    e.preventDefault();
    if (!newPersonName.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/people`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newPersonName.trim() }),
      });
      const data = await res.json();
      if (data.ok) { setNewPersonName(""); fetchPeople(); }
    } catch { /* ignore */ }
  }

  async function removePerson(id) {
    try {
      await fetch(`${API_BASE}/api/people/${id}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      fetchPeople();
    } catch { /* ignore */ }
  }

  async function assignCluster(clusterId, faces) {
    const name = (clusterNames[clusterId] || "").trim();
    if (!name || !faces?.length) return;
    try {
      // Create person, then assign all faces in the cluster
      const personRes = await fetch(`${API_BASE}/api/people`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const personData = await personRes.json();
      if (!personData.ok) return;
      const personId = personData.person_id;

      for (const face of faces) {
        if (face.id) {
          await fetch(`${API_BASE}/api/faces/${face.id}/assign`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ person_id: personId }),
          });
        }
      }
      setClusterNames(prev => ({ ...prev, [clusterId]: "" }));
      fetchPeople();
      fetchFaceClusters();
    } catch { /* ignore */ }
  }

  // ── Review functions ────────────────────────────────────────────────
  async function acceptReview(reviewId, categoryId) {
    try {
      await fetch(`${API_BASE}/api/review-queue/${reviewId}/resolve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: categoryId }),
      });
      fetchReviewQueue();
    } catch { /* ignore */ }
  }

  async function handlePurge() {
    if (purgeConfirm !== "PURGE") { setError("Type PURGE to confirm"); return; }
    setPurgeBusy(true);
    try {
      await fetch(`${API_BASE}/api/faces/purge`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: "PURGE" }),
      });
      setPurgeConfirm("");
      fetchPeople();
      fetchFaceClusters();
    } catch { /* ignore */ }
    setPurgeBusy(false);
  }

  // ── Cloud Sync functions ────────────────────────────────────────────
  async function fetchCloudAccounts() {
    try {
      const res = await fetch(`${API_BASE}/api/cloud/accounts`);
      const data = await res.json();
      if (data.ok) setCloudAccounts(data.accounts || []);
    } catch { /* ignore */ }
  }

  async function fetchSyncHistory() {
    try {
      const res = await fetch(`${API_BASE}/api/cloud/sync/history`);
      const data = await res.json();
      if (data.ok) setSyncHistory(data.runs || []);
    } catch { /* ignore */ }
  }

  async function connectGoogleDrive() {
    setSyncConnecting(true);
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/cloud/accounts/gdrive/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to start OAuth");

      // Open auth URL in a new tab
      window.open(data.auth_url, "_blank");

      // Poll for new account appearing
      const pollInterval = setInterval(async () => {
        const r = await fetch(`${API_BASE}/api/cloud/accounts`);
        const d = await r.json();
        if (d.ok && d.accounts.length > cloudAccounts.length) {
          clearInterval(pollInterval);
          setCloudAccounts(d.accounts);
          setSyncConnecting(false);
        }
      }, 2000);

      // Stop polling after 5 minutes
      setTimeout(() => {
        clearInterval(pollInterval);
        setSyncConnecting(false);
      }, 300000);
    } catch (err) {
      setError(err.message || "Failed to connect Google Drive");
      setSyncConnecting(false);
    }
  }

  async function disconnectCloudAccount(accountId) {
    if (!confirm("Disconnect this cloud account? This will revoke access.")) return;
    try {
      await fetch(`${API_BASE}/api/cloud/accounts/${accountId}`, { method: "DELETE" });
      fetchCloudAccounts();
    } catch (err) {
      setError(err.message || "Failed to disconnect account");
    }
  }

  async function startCloudSync(e) {
    e.preventDefault();
    setError("");
    if (!syncSelectedAccount) { setError("Select a cloud account"); return; }
    if (!syncSource.trim()) { setError("Source folder is required"); return; }

    try {
      // Create config
      const configRes = await fetch(`${API_BASE}/api/cloud/sync/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_id: Number(syncSelectedAccount),
          source_dir: syncSource.trim(),
          remote_path: syncRemotePath.trim() || "Clean-Backup",
          folder_scheme: syncFolderScheme,
          sync_type: syncType,
          duplicate_handling: syncDuplicateHandling,
          throttle_kb: Number(syncThrottleKb) || 0,
        }),
      });
      const configData = await configRes.json();
      if (!configData.ok) throw new Error(configData.error || "Failed to save config");

      // Start sync job
      const startRes = await fetch(`${API_BASE}/api/cloud/sync/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: configData.run_id }),
      });
      const startData = await startRes.json();
      if (!startData.ok) throw new Error(startData.error || "Failed to start sync");

      setSyncJobId(startData.job_id);
      setSyncRunId(configData.run_id);
    } catch (err) {
      setError(err.message || "Failed to start cloud sync");
    }
  }

  async function undoSyncRun(runId) {
    if (!confirm("This will DELETE all uploaded files from the cloud. Local files are unaffected. Continue?")) return;
    setError("");
    try {
      const res = await fetch(`${API_BASE}/api/cloud/sync/${runId}/undo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to start undo");
      setSyncUndoJobId(data.job_id);
    } catch (err) {
      setError(err.message || "Failed to undo sync");
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
        <h1>Clean-Backup</h1>
      </header>

      <section className="panel tab-panel">
        <div className="tab-row">
          <button className={`tab-btn ${activeTab === "duplicates" ? "active" : ""}`} onClick={() => setActiveTab("duplicates")}>Duplicates</button>
          <button className={`tab-btn ${activeTab === "organize" ? "active" : ""}`} onClick={() => setActiveTab("organize")}>Organize</button>
          <button className={`tab-btn ${activeTab === "compression" ? "active" : ""}`} onClick={() => setActiveTab("compression")}>Compression</button>
          <button className={`tab-btn ${activeTab === "classify" ? "active" : ""}`} onClick={() => { setActiveTab("classify"); fetchCategories(); }}>Classify</button>
          <button className={`tab-btn ${activeTab === "people" ? "active" : ""}`} onClick={() => { setActiveTab("people"); fetchPeople(); fetchFaceClusters(); }}>People</button>
          <button className={`tab-btn ${activeTab === "review" ? "active" : ""}`} onClick={() => { setActiveTab("review"); fetchReviewQueue(); }}>Review</button>
          <button className={`tab-btn ${activeTab === "cloud" ? "active" : ""}`} onClick={() => { setActiveTab("cloud"); fetchCloudAccounts(); fetchSyncHistory(); }}>Cloud Sync</button>
          <button className={`tab-btn ${activeTab === "watchers" ? "active" : ""}`} onClick={() => setActiveTab("watchers")}>Watchers</button>
          <button className={`tab-btn ${activeTab === "settings" ? "active" : ""}`} onClick={() => setActiveTab("settings")}>Settings</button>
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
                <div><span>Scan time</span><strong>{formatSeconds(scanSummary.scan_time_seconds)}</strong></div>
                <div><span>Core scan</span><strong>{formatSeconds(scanSummary.core_scan_seconds)}</strong></div>
                <div><span>Payload build</span><strong>{formatSeconds(scanSummary.payload_time_seconds)}</strong></div>
                <div><span>Collection</span><strong>{formatSeconds(scanSummary.collection_time_seconds)}</strong></div>
                <div><span>Hashing</span><strong>{formatSeconds(scanSummary.hash_time_seconds)}</strong></div>
                <div><span>Grouping</span><strong>{formatSeconds(scanSummary.group_time_seconds)}</strong></div>
                <div><span>Files walked</span><strong>{scanSummary.files_seen ?? 0}</strong></div>
                <div><span>Images found</span><strong>{scanSummary.images_found ?? 0}</strong></div>
                <div><span>Hashes fetched</span><strong>{scanSummary.hashes_fetched ?? 0}</strong></div>
                <div><span>Images without hash</span><strong>{scanSummary.images_without_hash ?? 0}</strong></div>
                <div><span>Hash success</span><strong>{formatPercent(scanSummary.hash_success_rate_pct)}</strong></div>
                <div><span>Avg images/group</span><strong>{Number(scanSummary.avg_images_per_group || 0).toFixed(2)}</strong></div>
                <div><span>Duplicate ratio</span><strong>{formatPercent(scanSummary.duplicate_ratio_pct)}</strong></div>
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
                    <button onClick={() => toggleGroupSelection(group)}>
                      {isGroupFullySelected(group) ? "Deselect group" : "Select group"}
                    </button>
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

      {activeTab === "classify" ? (
        <section className="panel">
          <h2>Content-Based Classification</h2>
          <form onSubmit={startClassify}>
            <label>
              Source folder
              <div className="path-input-row">
                <input type="text" value={clsSource} onChange={(e) => setClsSource(e.target.value)} placeholder="/path/to/photos" />
                <button type="button" className="secondary browse-btn" onClick={() => pickFolder("cls_source", clsSource, setClsSource)} disabled={Boolean(clsJobId) || Boolean(pickerBusyKey)}>
                  {pickerBusyKey === "cls_source" ? "Opening..." : "Select Folder"}
                </button>
              </div>
            </label>

            <h3 style={{ marginTop: 16, fontFamily: "'Space Grotesk', sans-serif" }}>Categories to detect</h3>
            <div className="category-grid">
              {clsCategories.map(cat => (
                <label key={cat.id} className="category-toggle">
                  <input type="checkbox" checked={Boolean(cat.default_enabled)} onChange={() => toggleCategory(cat.id)} />
                  <span className="category-icon">{CATEGORY_ICONS[cat.key] || "📁"}</span>
                  <span>{cat.label}</span>
                </label>
              ))}
            </div>

            <div className="wizard-grid">
              <label>
                Folder scheme
                <select value={clsFolderScheme} onChange={(e) => setClsFolderScheme(e.target.value)}>
                  <option value="yyyy_mm_category">YYYY/MM/Category</option>
                  <option value="category_yyyy_mm">Category/YYYY/MM</option>
                  <option value="flat_tags">Flat + Tags</option>
                </select>
              </label>
              <label>
                Multi-category handling
                <select value={clsMultiCategory} onChange={(e) => setClsMultiCategory(e.target.value)}>
                  <option value="tags">Tag-based (recommended)</option>
                  <option value="symlink">Symlinks</option>
                  <option value="primary">Primary category only</option>
                </select>
              </label>
              <label>
                Face recognition sensitivity
                <select value={clsFaceSensitivity} onChange={(e) => setClsFaceSensitivity(e.target.value)}>
                  <option value="strict">Strict (fewer matches)</option>
                  <option value="balanced">Balanced</option>
                  <option value="loose">Loose (more matches)</option>
                </select>
              </label>
              <label>
                Confidence threshold
                <div className="confidence-slider">
                  <input type="range" min="0.3" max="0.9" step="0.05" value={clsConfidence} onChange={(e) => setClsConfidence(e.target.value)} />
                  <span className="value-label">{Number(clsConfidence).toFixed(2)}</span>
                </div>
              </label>
              <label>
                Home GPS Latitude
                <input type="text" value={clsHomeLat} onChange={(e) => setClsHomeLat(e.target.value)} placeholder="e.g. 12.9716" />
              </label>
              <label>
                Home GPS Longitude
                <input type="text" value={clsHomeLon} onChange={(e) => setClsHomeLon(e.target.value)} placeholder="e.g. 77.5946" />
              </label>
            </div>

            <div style={{ marginTop: 14 }}>
              <button className="primary" type="submit" disabled={Boolean(clsJobId)}>
                {clsJobId ? "Classifying…" : "Start Classification"}
              </button>
            </div>
          </form>

          <JobProgress title="Classification" job={clsJob} />

          {clsJob && clsJob.status === "running" ? (
            <div className="stage-progress">
              {STAGE_NAMES.map(stage => {
                const active = getActiveStage(clsJob.message);
                const stageIdx = STAGE_NAMES.indexOf(stage);
                const activeIdx = active ? STAGE_NAMES.indexOf(active) : -1;
                let cls = "stage-step";
                if (stageIdx < activeIdx) cls += " done";
                else if (stage === active) cls += " active";
                return <div key={stage} className={cls}>{stage}</div>;
              })}
            </div>
          ) : null}

          {clsResult ? (
            <div className="result-panel">
              <h3>Classification Summary</h3>
              <div className="kv-grid">
                <div><span>Total files</span><strong>{clsResult.total_files}</strong></div>
                <div><span>Tags assigned</span><strong>{clsResult.tags_assigned}</strong></div>
                <div><span>Needs review</span><strong>{clsResult.review_items}</strong></div>
              </div>
              {clsResult.categories_found && Object.keys(clsResult.categories_found).length > 0 ? (
                <div className="results-chart">
                  {Object.entries(clsResult.categories_found).sort((a, b) => b[1] - a[1]).map(([key, count]) => {
                    const maxCount = Math.max(...Object.values(clsResult.categories_found));
                    const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                    return (
                      <div key={key} className="chart-row">
                        <span className="chart-label">{CATEGORY_ICONS[key] || ""} {key}</span>
                        <div className="chart-bar-wrap"><div className="chart-bar" style={{ width: `${pct}%` }} /></div>
                        <span className="chart-count">{count}</span>
                      </div>
                    );
                  })}
                </div>
              ) : null}

              <div style={{ marginTop: 24, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
                <h3>Apply Organization</h3>
                <p className="subtle" style={{ marginBottom: 12 }}>
                  Move or copy your classified files into physical folders based on your chosen scheme.
                </p>
                <form onSubmit={startApply}>
                  <label>
                    Destination folder
                    <div className="path-input-row">
                      <input type="text" value={clsDest} onChange={(e) => setClsDest(e.target.value)} placeholder="/path/to/destination" />
                      <button type="button" className="secondary browse-btn" onClick={() => pickFolder("cls_dest", clsDest, setClsDest)} disabled={Boolean(clsApplyJobId) || Boolean(pickerBusyKey)}>
                        {pickerBusyKey === "cls_dest" ? "Opening..." : "Select Folder"}
                      </button>
                    </div>
                  </label>
                  
                  <label style={{ marginTop: 10 }}>
                    Operation
                    <select value={clsOperation} onChange={(e) => setClsOperation(e.target.value)}>
                      <option value="move">Move files (faster, saves space)</option>
                      <option value="copy">Copy files (safer, keeps original)</option>
                    </select>
                  </label>
                  
                  <div style={{ marginTop: 14 }}>
                    <button className="primary" type="submit" disabled={Boolean(clsApplyJobId)}>
                      {clsApplyJobId ? "Applying…" : "Apply Organization"}
                    </button>
                  </div>
                </form>
                <JobProgress title="Apply Organization" job={clsApplyJob} />
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeTab === "people" ? (
        <section className="panel">
          <h2>People Management</h2>

          <form onSubmit={addPerson} className="new-person-row">
            <label style={{ flex: 1 }}>
              Add new person
              <input type="text" value={newPersonName} onChange={(e) => setNewPersonName(e.target.value)} placeholder="Person name" />
            </label>
            <button className="primary" type="submit">Add Person</button>
          </form>

          {people.length > 0 ? (
            <div className="people-grid">
              {people.map(person => (
                <div key={person.id} className="person-card">
                  {person.cover_face_id ? (
                    <img src={`${API_BASE}/api/face-crop?id=${person.cover_face_id}`} alt={person.name} />
                  ) : (
                    <div style={{ width: "100%", aspectRatio: 1, background: "#eaf0ef", display: "grid", placeItems: "center", fontSize: "2rem" }}>👤</div>
                  )}
                  <div className="person-name">{person.name}</div>
                  <div className="person-actions">
                    <button className="danger" onClick={() => removePerson(person.id)}>Remove</button>
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="empty-state" style={{ marginTop: 12 }}>No known people yet. Run a classify job with face detection enabled, or add manually above.</div>}

          <h3 style={{ marginTop: 24, fontFamily: "'Space Grotesk', sans-serif" }}>Unidentified Faces</h3>
          <button onClick={fetchFaceClusters} style={{ marginBottom: 10 }}>Refresh Clusters</button>

          {faceClusters.length === 0 ? (
            <div className="empty-state">No unidentified face clusters. Run a classify job with face detection enabled.</div>
          ) : (
            <div className="face-clusters">
              {faceClusters.map(cluster => (
                <div key={cluster.id} className="face-cluster-card">
                  <div className="face-cluster-preview">
                    {cluster.faces.slice(0, 6).map(face => (
                      <img key={face.id} src={`${API_BASE}/api/face-crop?id=${face.id}`} alt="face" />
                    ))}
                  </div>
                  <div className="face-cluster-label">
                    <span>{cluster.count} photo{cluster.count !== 1 ? "s" : ""}</span>
                    <input
                      type="text"
                      placeholder="Who is this?"
                      value={clusterNames[cluster.id] || ""}
                      onChange={(e) => setClusterNames(prev => ({ ...prev, [cluster.id]: e.target.value }))}
                    />
                    <button className="primary" onClick={() => assignCluster(cluster.id, cluster.faces)}>Save</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {activeTab === "review" ? (
        <section className="panel">
          <h2>Review Queue</h2>
          <div className="review-filter-bar">
            {["all", "scene", "document", "face"].map(f => (
              <button
                key={f}
                className={reviewFilter === f ? "active" : ""}
                onClick={() => { setReviewFilter(f); setTimeout(fetchReviewQueue, 50); }}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>

          {reviewQueue.length === 0 ? (
            <div className="empty-state">No items need review. Run a classify job to populate this queue.</div>
          ) : (
            <div className="review-grid">
              {reviewQueue.map(item => (
                <div key={item.id} className="review-card">
                  <img src={imageUrl(item.path, "thumb")} alt={item.filename} />
                  <div className="review-meta">
                    {item.suggested_label ? <span className="suggested-tag">{item.suggested_label}</span> : null}
                    <div className="review-confidence">Confidence: {((item.confidence || 0) * 100).toFixed(0)}%</div>
                  </div>
                  <div className="review-actions">
                    {item.suggested_category_id ? (
                      <button className="primary" onClick={() => acceptReview(item.id, item.suggested_category_id)}>Accept</button>
                    ) : null}
                    <select onChange={(e) => { if (e.target.value) acceptReview(item.id, Number(e.target.value)); e.target.value = ""; }}>
                      <option value="">Reassign…</option>
                      {clsCategories.map(cat => <option key={cat.id} value={cat.id}>{cat.label}</option>)}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      ) : null}
      {activeTab === "watchers" ? (
        <WatcherSettings />
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

          <details className="advanced-settings">
            <summary>Category Settings (Advanced)</summary>
            <div className="category-settings-grid">
              {clsCategories.map(cat => (
                <div key={cat.id} className="category-setting-row">
                  <input type="checkbox" checked={Boolean(cat.default_enabled)} onChange={() => {
                    fetch(`${API_BASE}/api/categories/${cat.id}`, {
                      method: "PATCH", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ enabled: !cat.default_enabled }),
                    }).then(() => fetchCategories());
                  }} />
                  <span>{CATEGORY_ICONS[cat.key] || ""} {cat.label}</span>
                  <input type="number" defaultValue={cat.priority} min={0} max={99} onBlur={(e) => {
                    fetch(`${API_BASE}/api/categories/${cat.id}`, {
                      method: "PATCH", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ priority: Number(e.target.value) }),
                    }).then(() => fetchCategories());
                  }} />
                </div>
              ))}
            </div>
          </details>

          <div className="danger-zone">
            <h3>⚠️ Danger Zone</h3>
            <p>Permanently delete all face embeddings and people data. Manual review tags will be preserved.</p>
            <div className="purge-row">
              <label>
                Type PURGE to confirm
                <input type="text" value={purgeConfirm} onChange={(e) => setPurgeConfirm(e.target.value)} placeholder="PURGE" />
              </label>
              <button className="danger" onClick={handlePurge} disabled={purgeBusy}>Purge All Face Data</button>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "cloud" ? (
        <section className="panel">
          <h2>☁️ Cloud Sync</h2>
          <p className="subtle">Push your organized files to Google Drive or AWS S3.</p>

          {/* ── Connected Accounts ──────────────────────────────── */}
          <div style={{ marginBottom: 24 }}>
            <h3>Connected Accounts</h3>
            {cloudAccounts.length === 0 ? (
              <div className="empty-state">No cloud accounts connected yet.</div>
            ) : (
              <div className="cloud-accounts-grid">
                {cloudAccounts.map(acc => (
                  <div key={acc.id} className="cloud-account-card">
                    <div className="cloud-account-icon">{acc.provider === "gdrive" ? "📁" : "☁️"}</div>
                    <div className="cloud-account-info">
                      <div className="cloud-account-label">{acc.label}</div>
                      <div className="subtle">{acc.provider === "gdrive" ? "Google Drive" : "AWS S3"}</div>
                    </div>
                    <button className="danger small" onClick={() => disconnectCloudAccount(acc.id)}>Disconnect</button>
                  </div>
                ))}
              </div>
            )}
            <div style={{ marginTop: 12, display: "flex", gap: 10 }}>
              <button className="primary" onClick={connectGoogleDrive} disabled={syncConnecting}>
                {syncConnecting ? "Connecting…" : "Connect Google Drive"}
              </button>
              <button className="secondary" disabled title="Coming soon">
                Connect AWS S3
              </button>
            </div>
          </div>

          {/* ── Sync Wizard ─────────────────────────────────────── */}
          {cloudAccounts.length > 0 ? (
            <div style={{ paddingTop: 16, borderTop: "1px solid var(--line)" }}>
              <h3>Start a Sync</h3>
              <form onSubmit={startCloudSync}>
                <label>
                  Account
                  <select value={syncSelectedAccount} onChange={(e) => setSyncSelectedAccount(e.target.value)}>
                    <option value="">Select account…</option>
                    {cloudAccounts.map(acc => (
                      <option key={acc.id} value={acc.id}>{acc.label} ({acc.provider === "gdrive" ? "Google Drive" : "S3"})</option>
                    ))}
                  </select>
                </label>

                <label>
                  Source folder
                  <div className="path-input-row">
                    <input type="text" value={syncSource} onChange={(e) => setSyncSource(e.target.value)} placeholder="/path/to/organized/photos" />
                    <button type="button" className="secondary browse-btn" onClick={() => pickFolder("sync_source", syncSource, setSyncSource)} disabled={Boolean(pickerBusyKey)}>
                      {pickerBusyKey === "sync_source" ? "Opening..." : "Select Folder"}
                    </button>
                  </div>
                </label>

                <label>
                  Remote destination path
                  <input type="text" value={syncRemotePath} onChange={(e) => setSyncRemotePath(e.target.value)} placeholder="Clean-Backup" />
                </label>

                <label>
                  Folder structure
                  <select value={syncFolderScheme} onChange={(e) => setSyncFolderScheme(e.target.value)}>
                    <option value="mirror">Mirror local folder structure</option>
                    <option value="flat">Flat (all files in destination root)</option>
                  </select>
                </label>

                <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                  <label style={{ flex: 1, minWidth: 180 }}>
                    Sync type
                    <select value={syncType} onChange={(e) => setSyncType(e.target.value)}>
                      <option value="incremental">Incremental (only new/changed)</option>
                      <option value="full">Full re-upload</option>
                    </select>
                  </label>

                  <label style={{ flex: 1, minWidth: 180 }}>
                    Duplicate handling
                    <select value={syncDuplicateHandling} onChange={(e) => setSyncDuplicateHandling(e.target.value)}>
                      <option value="skip">Skip (if hash matches)</option>
                      <option value="overwrite">Overwrite</option>
                      <option value="rename">Rename with suffix</option>
                    </select>
                  </label>
                </div>

                <label>
                  Bandwidth throttle (KB/s, 0 = unlimited)
                  <input type="number" min="0" value={syncThrottleKb} onChange={(e) => setSyncThrottleKb(e.target.value)} placeholder="0" />
                </label>

                <div style={{ marginTop: 14 }}>
                  <button className="primary" type="submit" disabled={Boolean(syncJobId) || !syncSelectedAccount}>
                    {syncJobId ? "Syncing…" : "Start Sync"}
                  </button>
                </div>
              </form>
              <JobProgress title="Cloud Sync" job={syncJob} />
            </div>
          ) : null}

          {/* ── Sync History ────────────────────────────────────── */}
          {syncHistory.length > 0 ? (
            <div style={{ marginTop: 24, paddingTop: 16, borderTop: "1px solid var(--line)" }}>
              <h3>Sync History</h3>
              <div className="session-list">
                {syncHistory.map(run => (
                  <div key={run.id} className="session-row">
                    <div>
                      <div className="session-id">
                        {run.account_label || "Account"} — {run.started_at ? new Date(run.started_at).toLocaleString() : "Pending"}
                      </div>
                      <div className="subtle">
                        <span className={`sync-status sync-status-${run.status}`}>{run.status}</span>
                        {" · "}{run.uploaded || 0} uploaded, {run.skipped || 0} skipped, {run.failed || 0} failed
                      </div>
                    </div>
                    {run.can_undo ? (
                      <button className="danger" onClick={() => undoSyncRun(run.id)} disabled={Boolean(syncUndoJobId)}>Undo</button>
                    ) : null}
                  </div>
                ))}
              </div>
              <JobProgress title="Undo Cloud Sync" job={syncUndoJob} />
            </div>
          ) : null}
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

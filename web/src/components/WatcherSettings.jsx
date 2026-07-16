import React, { useState, useEffect } from 'react';

const API_BASE = "";

export default function WatcherSettings() {
  const [watchers, setWatchers] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Form state for a new watcher
  const [label, setLabel] = useState('');
  const [watchPath, setWatchPath] = useState('');
  const [pipelineStep, setPipelineStep] = useState('classify');
  const [pipeline, setPipeline] = useState([]);

  useEffect(() => {
    fetchWatchers();
  }, []);

  const fetchWatchers = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/watchers`);
      if (!res.ok) throw new Error('Failed to fetch');
      const data = await res.json();
      setWatchers(data.watchers || []);
      setEvents(data.events || []);
    } catch (err) {
      setError('Failed to fetch watchers.');
    } finally {
      setLoading(false);
    }
  };

  const handleAddWatcher = async (e) => {
    e.preventDefault();
    if (!watchPath.trim()) return alert("Watch path is required");

    try {
      const res = await fetch(`${API_BASE}/api/watchers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label: label || 'New Watcher',
          watch_path: watchPath,
          pipeline: pipeline,
          enabled: true,
          recursive: true,
          stability_window_seconds: 3,
        }),
      });
      if (!res.ok) throw new Error('Failed to create watcher');
      setLabel('');
      setWatchPath('');
      setPipeline([]);
      fetchWatchers();
    } catch (err) {
      alert(err.message || "Failed to create watcher");
    }
  };

  const addPipelineStep = () => {
    setPipeline([...pipeline, { job_type: pipelineStep, enabled: true }]);
  };

  const removePipelineStep = (index) => {
    setPipeline(pipeline.filter((_, i) => i !== index));
  };

  const toggleWatcher = async (id, currentEnabled) => {
    try {
      const res = await fetch(`${API_BASE}/api/watchers/${id}/${currentEnabled ? 'stop' : 'start'}`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error('Failed to toggle');
      fetchWatchers();
    } catch (err) {
      alert("Failed to toggle watcher");
    }
  };

  const deleteWatcher = async (id) => {
    if (!window.confirm("Delete this watcher?")) return;
    try {
      const res = await fetch(`${API_BASE}/api/watchers/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete');
      fetchWatchers();
    } catch (err) {
      alert("Failed to delete watcher");
    }
  };

  if (loading) return <div className="p-8 text-center text-gray-500">Loading watchers...</div>;

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-8 animate-fade-in">
      <div>
        <h1 className="text-3xl font-light text-gray-800 mb-2">Watchers</h1>
        <p className="text-gray-500">
          Automatically run pipelines when new files are dropped into specific folders.
        </p>
      </div>

      {error && <div className="bg-red-50 text-red-600 p-4 rounded-lg">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="space-y-6">
          <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
            <h2 className="text-lg font-medium text-gray-800 mb-4">Create Watcher</h2>
            <form onSubmit={handleAddWatcher} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Label</label>
                <input
                  type="text"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="e.g., SD Card Drop"
                  className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Watch Folder Path *</label>
                <input
                  type="text"
                  value={watchPath}
                  onChange={(e) => setWatchPath(e.target.value)}
                  placeholder="/path/to/watch"
                  className="w-full px-4 py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none transition-all"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Pipeline Steps</label>
                <div className="flex items-center gap-2 mb-2">
                  <select
                    value={pipelineStep}
                    onChange={(e) => setPipelineStep(e.target.value)}
                    className="flex-1 px-4 py-2 border border-gray-200 rounded-lg outline-none"
                  >
                    <option value="classify">Classify</option>
                    <option value="organize-by-date">Organize by Date</option>
                    <option value="dedupe">Deduplicate</option>
                    <option value="cloud_sync">Cloud Sync</option>
                  </select>
                  <button
                    type="button"
                    onClick={addPipelineStep}
                    className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors font-medium"
                  >
                    Add Step
                  </button>
                </div>
                
                {pipeline.length > 0 ? (
                  <ul className="space-y-2">
                    {pipeline.map((step, idx) => (
                      <li key={idx} className="flex justify-between items-center p-3 bg-gray-50 rounded-lg border border-gray-100">
                        <span className="font-medium text-gray-700">
                          {idx + 1}. {step.job_type}
                        </span>
                        <button
                          type="button"
                          onClick={() => removePipelineStep(idx)}
                          className="text-red-500 hover:text-red-700 text-sm font-medium"
                        >
                          Remove
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-gray-500 italic">No steps added yet.</p>
                )}
              </div>

              <div className="pt-4 border-t border-gray-100">
                <button
                  type="submit"
                  disabled={pipeline.length === 0}
                  className="w-full py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium disabled:opacity-50"
                >
                  Create Watcher
                </button>
              </div>
            </form>
          </div>
        </div>

        <div className="space-y-6">
          <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
            <h2 className="text-lg font-medium text-gray-800 mb-4">Active Watchers</h2>
            {watchers.length === 0 ? (
              <p className="text-gray-500 text-center py-8">No watchers configured.</p>
            ) : (
              <ul className="space-y-4">
                {watchers.map((w) => (
                  <li key={w.id} className="p-4 rounded-xl border border-gray-100 shadow-sm relative overflow-hidden group">
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <h3 className="font-semibold text-gray-800">{w.label}</h3>
                        <p className="text-sm text-gray-500 truncate max-w-[250px]" title={w.watch_path}>
                          {w.watch_path}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => toggleWatcher(w.id, w.enabled)}
                          className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                            w.enabled 
                              ? 'bg-green-100 text-green-700 hover:bg-green-200' 
                              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                          }`}
                        >
                          {w.enabled ? 'Active' : 'Paused'}
                        </button>
                        <button
                          onClick={() => deleteWatcher(w.id)}
                          className="px-3 py-1 rounded-full text-xs font-medium bg-red-50 text-red-600 hover:bg-red-100 transition-colors opacity-0 group-hover:opacity-100"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                    <div className="flex gap-1 flex-wrap mt-3">
                      {w.pipeline.map((step, idx) => (
                        <span key={idx} className="px-2 py-1 bg-blue-50 text-blue-700 rounded text-[10px] font-bold uppercase tracking-wider">
                          {step.job_type}
                        </span>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
            <h2 className="text-lg font-medium text-gray-800 mb-4">Recent Events</h2>
            {events.length === 0 ? (
              <p className="text-gray-500 text-center py-8">No recent activity.</p>
            ) : (
              <div className="space-y-3 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                {events.map((e) => (
                  <div key={e.id} className="text-sm p-3 rounded-lg bg-gray-50 border border-gray-100">
                    <div className="flex justify-between mb-1">
                      <span className="font-medium text-gray-700">{e.watcher_label}</span>
                      <span className={`text-xs font-medium ${
                        e.status === 'completed' ? 'text-green-600' : 
                        e.status === 'failed' ? 'text-red-600' : 'text-blue-600'
                      }`}>
                        {e.status}
                      </span>
                    </div>
                    <p className="text-gray-500 text-xs truncate" title={e.file_path}>
                      {e.file_path.split('/').pop()}
                    </p>
                    <p className="text-gray-400 text-[10px] mt-1 text-right">
                      {new Date(e.detected_at).toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

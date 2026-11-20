import { useEffect, useMemo, useState } from "react";

const API = import.meta.env.VITE_API_URL || "";

const WEIGHT_KEYS = [
  "Resilience_Reduction_%",
  "Path_Frequency_%",
  "Flow_Criticality_%",
  "Betweenness_Centrality_%",
  "Demand_Coverage_%",
];

function Sparkline({ values, color = "#0f6b4c" }) {
  const points = useMemo(() => {
    if (!values?.length) return "";
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    return values
      .map((v, i) => {
        const x = (i / Math.max(values.length - 1, 1)) * 100;
        const y = 100 - ((v - min) / span) * 90 - 5;
        return `${x},${y}`;
      })
      .join(" ");
  }, [values]);

  if (!values?.length) return <div className="spark" />;
  return (
    <svg className="spark" viewBox="0 0 100 100" preserveAspectRatio="none">
      <polyline fill="none" stroke={color} strokeWidth="2" points={points} />
    </svg>
  );
}

function downloadText(filename, text) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function App() {
  const [file, setFile] = useState(null);
  const [defaults, setDefaults] = useState(null);
  const [minHead, setMinHead] = useState(18);
  const [weights, setWeights] = useState({});
  const [criticalNodesText, setCriticalNodesText] = useState("{}");
  const [opt, setOpt] = useState({
    min_pressure: 18,
    pipe_sizes_mm: "100,200,300,400,500,600,700",
    pipe_costs: "50,90,140,210,355,430,650",
    n_gen: 20,
    pop_size: 30,
    cxpb: 0.7,
    mutpb: 0.2,
    indpb: 0.1,
    seed: "",
  });

  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [optResult, setOptResult] = useState(null);

  useEffect(() => {
    fetch(`${API}/api/defaults`)
      .then((r) => r.json())
      .then((d) => {
        setDefaults(d);
        setMinHead(d.criticality.min_head);
        setWeights(d.criticality.composite_weights);
        setCriticalNodesText(JSON.stringify(d.criticality.critical_nodes, null, 2));
        const o = d.optimization;
        setOpt({
          min_pressure: o.min_pressure,
          pipe_sizes_mm: o.pipe_sizes_mm.join(","),
          pipe_costs: o.pipe_costs.join(","),
          n_gen: o.n_gen,
          pop_size: o.pop_size,
          cxpb: o.cxpb,
          mutpb: o.mutpb,
          indpb: o.indpb,
          seed: "",
        });
      })
      .catch((e) => setError(`Could not load defaults: ${e.message}`));
  }, []);

  async function runAnalyze() {
    setError("");
    setAnalysis(null);
    if (!file) {
      setError("Choose an EPANET .inp file first.");
      return;
    }
    let nodes;
    try {
      nodes = JSON.parse(criticalNodesText);
    } catch {
      setError("Critical nodes JSON is invalid.");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("min_head", String(minHead));
    form.append("composite_weights", JSON.stringify(weights));
    form.append("critical_nodes", JSON.stringify(nodes));
    setBusy("analyze");
    try {
      const res = await fetch(`${API}/api/analyze`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      setAnalysis(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function runOptimize() {
    setError("");
    setOptResult(null);
    if (!file) {
      setError("Choose an EPANET .inp file first.");
      return;
    }
    const parseList = (s) =>
      String(s)
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean)
        .map(Number);

    const settings = {
      min_pressure: Number(opt.min_pressure),
      pipe_sizes_mm: parseList(opt.pipe_sizes_mm),
      pipe_costs: parseList(opt.pipe_costs),
      n_gen: Number(opt.n_gen),
      pop_size: Number(opt.pop_size),
      cxpb: Number(opt.cxpb),
      mutpb: Number(opt.mutpb),
      indpb: Number(opt.indpb),
      seed: opt.seed === "" ? null : Number(opt.seed),
    };
    if (settings.pipe_sizes_mm.length !== settings.pipe_costs.length) {
      setError("pipe_sizes_mm and pipe_costs must have the same count.");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    form.append("settings", JSON.stringify(settings));
    setBusy("optimize");
    try {
      const res = await fetch(`${API}/api/optimize`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      setOptResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  const topPipes = analysis?.pipes?.slice(0, 50) ?? [];

  return (
    <>
      <header className="hero">
        <h1>WDN Criticality</h1>
        <p>
          Upload an EPANET <code>.inp</code> network, compute pipe criticality measures from the
          Water Criticality Code, and run the existing DEAP pipe-sizing GA with its settings exposed.
        </p>
      </header>

      <section className="panel">
        <h2>Network file</h2>
        <div className="row">
          <label className="file-btn">
            Choose .inp
            <input
              type="file"
              accept=".inp"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
          <span className="muted">{file ? file.name : "No file selected"}</span>
        </div>
      </section>

      <div className="grid two" style={{ marginTop: "1rem" }}>
        <section className="panel">
          <h2>Criticality analysis</h2>
          <p className="muted">
            Metrics reuse <code>Water Criticality Code/WDN_Criticality.ipynb</code> (WNTR +
            importance-weighted surplus / path / flow / betweenness / demand → composite).
          </p>

          <div className="row">
            <div className="field">
              <label>Min head Hl (m)</label>
              <input
                type="number"
                value={minHead}
                step="0.1"
                onChange={(e) => setMinHead(Number(e.target.value))}
              />
            </div>
          </div>

          <h3 style={{ marginTop: "0.75rem", fontSize: "1rem" }}>Composite weights</h3>
          <div className="weights">
            {WEIGHT_KEYS.map((k) => (
              <div className="field" key={k}>
                <label>{k}</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={weights[k] ?? 0}
                  onChange={(e) =>
                    setWeights((w) => ({ ...w, [k]: Number(e.target.value) }))
                  }
                />
              </div>
            ))}
          </div>

          <h3 style={{ marginTop: "0.9rem", fontSize: "1rem" }}>Critical nodes JSON</h3>
          <p className="muted">
            Format: <code>{`{"16": {"structure": "Hospital", "importance": 4}}`}</code>
          </p>
          <textarea
            value={criticalNodesText}
            onChange={(e) => setCriticalNodesText(e.target.value)}
          />

          <div className="row">
            <button onClick={runAnalyze} disabled={busy === "analyze"}>
              {busy === "analyze" ? "Running analysis…" : "Run criticality"}
            </button>
          </div>
        </section>

        <section className="panel">
          <h2>Optimization (GA)</h2>
          <p className="muted">
            From <code>GA_WDN_Optimization.ipynb</code>: NSGA-II minimizing pipe cost and average
            pressure violation. Notebook scale was n_gen=500 / pop_size=200 — UI defaults are smaller
            for interactive runs.
          </p>

          <div className="row">
            <div className="field">
              <label>Min pressure (m)</label>
              <input
                type="number"
                value={opt.min_pressure}
                onChange={(e) => setOpt({ ...opt, min_pressure: e.target.value })}
              />
            </div>
            <div className="field">
              <label>n_gen</label>
              <input
                type="number"
                value={opt.n_gen}
                onChange={(e) => setOpt({ ...opt, n_gen: e.target.value })}
              />
            </div>
            <div className="field">
              <label>pop_size</label>
              <input
                type="number"
                value={opt.pop_size}
                onChange={(e) => setOpt({ ...opt, pop_size: e.target.value })}
              />
            </div>
          </div>

          <div className="row">
            <div className="field">
              <label>cxpb</label>
              <input
                type="number"
                step="0.05"
                value={opt.cxpb}
                onChange={(e) => setOpt({ ...opt, cxpb: e.target.value })}
              />
            </div>
            <div className="field">
              <label>mutpb</label>
              <input
                type="number"
                step="0.05"
                value={opt.mutpb}
                onChange={(e) => setOpt({ ...opt, mutpb: e.target.value })}
              />
            </div>
            <div className="field">
              <label>indpb</label>
              <input
                type="number"
                step="0.05"
                value={opt.indpb}
                onChange={(e) => setOpt({ ...opt, indpb: e.target.value })}
              />
            </div>
            <div className="field">
              <label>seed (optional)</label>
              <input
                type="number"
                value={opt.seed}
                onChange={(e) => setOpt({ ...opt, seed: e.target.value })}
              />
            </div>
          </div>

          <div className="field">
            <label>pipe_sizes_mm (comma-separated)</label>
            <input
              type="text"
              value={opt.pipe_sizes_mm}
              onChange={(e) => setOpt({ ...opt, pipe_sizes_mm: e.target.value })}
            />
          </div>
          <div className="field" style={{ marginTop: "0.55rem" }}>
            <label>pipe_costs $/m (comma-separated)</label>
            <input
              type="text"
              value={opt.pipe_costs}
              onChange={(e) => setOpt({ ...opt, pipe_costs: e.target.value })}
            />
          </div>

          <div className="row">
            <button onClick={runOptimize} disabled={busy === "optimize"}>
              {busy === "optimize" ? "Running GA…" : "Run optimization"}
            </button>
          </div>
        </section>
      </div>

      {error ? <div className="status error">{error}</div> : null}
      {busy ? (
        <div className="status">
          Working: {busy}. Pipe-by-pipe resilience can take a while on large networks.
        </div>
      ) : null}

      {analysis ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>Criticality results</h2>
          <div className="stats">
            <div className="stat">
              <strong>{analysis.network.pipes}</strong>
              <span>Pipes</span>
            </div>
            <div className="stat">
              <strong>{analysis.network.junctions}</strong>
              <span>Junctions</span>
            </div>
            <div className="stat">
              <strong>{analysis.baseline.resilience_index_Ir.toFixed(4)}</strong>
              <span>Resilience Ir</span>
            </div>
            <div className="stat">
              <strong>{analysis.baseline.weighted_surplus_X.toFixed(4)}</strong>
              <span>Surplus X</span>
            </div>
          </div>
          <p className="muted">
            Classes:{" "}
            {Object.entries(analysis.class_distribution)
              .map(([k, v]) => `${k}=${v}`)
              .join(" · ")}
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Pipe</th>
                  <th>Composite</th>
                  <th>Class</th>
                  <th>Resil%</th>
                  <th>Path%</th>
                  <th>Flow%</th>
                  <th>BC%</th>
                  <th>Demand%</th>
                  <th>Seg</th>
                </tr>
              </thead>
              <tbody>
                {topPipes.map((p) => (
                  <tr key={p.Pipe_ID}>
                    <td>{p.Rank}</td>
                    <td>{p.Pipe_ID}</td>
                    <td>{p.Composite_Criticality}</td>
                    <td>{p.Criticality_Class}</td>
                    <td>{p["Resilience_Reduction_%"]}</td>
                    <td>{p["Path_Frequency_%"]}</td>
                    <td>{p["Flow_Criticality_%"]}</td>
                    <td>{p["Betweenness_Centrality_%"]}</td>
                    <td>{p["Demand_Coverage_%"]}</td>
                    <td>{p.Segment_Importance}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">Showing top {topPipes.length} of {analysis.pipes.length} pipes.</p>
        </section>
      ) : null}

      {optResult ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>Optimization results</h2>
          <div className="stats">
            <div className="stat">
              <strong>{optResult.best.cost.toFixed(1)}</strong>
              <span>Best cost</span>
            </div>
            <div className="stat">
              <strong>{optResult.best.violation.toFixed(4)}</strong>
              <span>Best violation (m)</span>
            </div>
            <div className="stat">
              <strong>{optResult.pareto_front.length}</strong>
              <span>Pareto solutions</span>
            </div>
          </div>
          <div className="history">
            <div>
              <small className="muted">Cost history</small>
              <Sparkline values={optResult.history.cost} />
            </div>
            <div>
              <small className="muted">Violation history</small>
              <Sparkline values={optResult.history.violation} color="#8a4b12" />
            </div>
          </div>
          <div className="row">
            <button
              className="secondary"
              onClick={() =>
                downloadText(
                  `${(file?.name || "network").replace(/\.inp$/i, "")}_optimized.inp`,
                  optResult.optimized_inp || ""
                )
              }
              disabled={!optResult.optimized_inp}
            >
              Download optimized .inp
            </button>
          </div>
        </section>
      ) : null}

      <footer>
        Reuses Water Criticality Code + GA_WDN_Optimization. Defaults loaded
        {defaults ? " from API." : "…"}
      </footer>
    </>
  );
}

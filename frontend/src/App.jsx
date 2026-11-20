import { useCallback, useEffect, useMemo, useState } from "react";
import Help from "./Help.jsx";
import NetworkMap from "./NetworkMap.jsx";
import { downloadText, n2, toCsv } from "./format.js";

const API = import.meta.env.VITE_API_URL || "";

const WEIGHT_KEYS = [
  "Resilience_Reduction_%",
  "Path_Frequency_%",
  "Flow_Criticality_%",
  "Betweenness_Centrality_%",
  "Demand_Coverage_%",
];

function Sparkline({ values, color = "#0f6b4c", labelMin, labelMax }) {
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
    <div>
      <svg className="spark" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline fill="none" stroke={color} strokeWidth="2" points={points} />
      </svg>
      <div className="spark-labels muted">
        <span>{n2(labelMin ?? Math.min(...values))}</span>
        <span>{n2(labelMax ?? Math.max(...values))}</span>
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("app");
  const [file, setFile] = useState(null);
  const [geometry, setGeometry] = useState(null);
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
  const [optLive, setOptLive] = useState(null);

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

  const loadNetwork = useCallback(async (f) => {
    if (!f) {
      setGeometry(null);
      return;
    }
    const form = new FormData();
    form.append("file", f);
    setBusy("network");
    setError("");
    try {
      const res = await fetch(`${API}/api/network`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      setGeometry(data);
      const od = data.optimization_defaults;
      if (od?.pipe_sizes_mm?.length && od?.pipe_costs?.length) {
        setOpt((prev) => ({
          ...prev,
          pipe_sizes_mm: od.pipe_sizes_mm.join(","),
          pipe_costs: od.pipe_costs.map((c) => Number(c).toFixed(2)).join(","),
        }));
      }
    } catch (e) {
      setError(e.message);
      setGeometry(null);
    } finally {
      setBusy(null);
    }
  }, []);

  async function onFileChange(e) {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setAnalysis(null);
    setOptResult(null);
    setOptLive(null);
    await loadNetwork(f);
  }

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
      if (data.geometry) setGeometry(data.geometry);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  async function runOptimize() {
    setError("");
    setOptResult(null);
    setOptLive(null);
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
      const res = await fetch(`${API}/api/optimize/stream`, { method: "POST", body: form });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.error || res.statusText);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const msg = JSON.parse(line);
          if (msg.event === "progress") {
            setOptLive(msg);
          } else if (msg.event === "done") {
            setOptResult(msg.result);
            setOptLive(null);
          } else if (msg.event === "error") {
            throw new Error(msg.error);
          }
        }
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  const topPipes = analysis?.pipes?.slice(0, 50) ?? [];
  const stem = (file?.name || "network").replace(/\.inp$/i, "");
  const liveHistory = optLive
    ? { cost: optLive.cost_history || [], violation: optLive.violation_history || [] }
    : optResult?.history;

  function exportCriticalityCsv() {
    if (!analysis?.pipes?.length) return;
    downloadText(`${stem}_criticality.csv`, toCsv(analysis.pipes), "text/csv;charset=utf-8");
  }

  function exportBaselineCsv() {
    if (!analysis) return;
    const row = {
      source_file: analysis.source_file,
      weighted_surplus_X: analysis.baseline.weighted_surplus_X,
      resilience_index_Ir: analysis.baseline.resilience_index_Ir,
      min_head_m: analysis.baseline.min_head_m,
      pipes: analysis.network.pipes,
      junctions: analysis.network.junctions,
      reservoirs: analysis.network.reservoirs,
    };
    downloadText(`${stem}_baseline.csv`, toCsv([row]), "text/csv;charset=utf-8");
  }

  function exportOptCsv() {
    if (!optResult) return;
    const hist = (optResult.history.cost || []).map((c, i) => ({
      generation: i,
      cost: c,
      violation: optResult.history.violation[i],
    }));
    downloadText(`${stem}_opt_history.csv`, toCsv(hist), "text/csv;charset=utf-8");
    downloadText(
      `${stem}_opt_pareto.csv`,
      toCsv(optResult.pareto_front || []),
      "text/csv;charset=utf-8"
    );
    const diameters = Object.entries(optResult.best.pipe_diameters_mm || {}).map(
      ([pipe_id, diameter_mm]) => ({ pipe_id, diameter_mm })
    );
    downloadText(`${stem}_opt_diameters.csv`, toCsv(diameters), "text/csv;charset=utf-8");
    downloadText(
      `${stem}_opt_best.csv`,
      toCsv([
        {
          cost: optResult.best.cost,
          violation: optResult.best.violation,
          n_pipes: optResult.n_pipes,
        },
      ]),
      "text/csv;charset=utf-8"
    );
  }

  if (tab === "help") {
    return (
      <>
        <nav className="tabs">
          <button type="button" className="secondary" onClick={() => setTab("app")}>
            App
          </button>
          <button type="button" onClick={() => setTab("help")}>
            Help
          </button>
        </nav>
        <Help />
      </>
    );
  }

  return (
    <>
      <nav className="tabs">
        <button type="button" onClick={() => setTab("app")}>
          App
        </button>
        <button type="button" className="secondary" onClick={() => setTab("help")}>
          Help
        </button>
      </nav>

      <header className="hero">
        <h1>WDN Criticality</h1>
        <p>
          Upload an EPANET <code>.inp</code>, view the network, compute Water Criticality Code
          metrics, and run the DEAP pipe-sizing GA with live objective progress. Numerics use two
          decimal places.
        </p>
      </header>

      <section className="panel">
        <h2>Network file</h2>
        <div className="row">
          <label className="file-btn">
            Choose .inp
            <input type="file" accept=".inp" onChange={onFileChange} />
          </label>
          <span className="muted">{file ? file.name : "No file selected"}</span>
        </div>
        {geometry ? (
          <>
            <p className="muted">
              {geometry.counts.nodes} nodes · {geometry.counts.pipes} pipes
              {analysis ? " · pipes colored by composite criticality after analysis" : ""}
            </p>
            <NetworkMap geometry={geometry} pipeScores={analysis?.pipes} />
          </>
        ) : null}
      </section>

      <div className="grid two" style={{ marginTop: "1rem" }}>
        <section className="panel">
          <h2>Criticality analysis</h2>
          <p className="muted">
            Reuses <code>WDN_Criticality.ipynb</code> (see Help for formulations).
          </p>

          <div className="row">
            <div className="field">
              <label>Min head Hl (m)</label>
              <input
                type="number"
                value={minHead}
                step="0.01"
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
                  onChange={(e) => setWeights((w) => ({ ...w, [k]: Number(e.target.value) }))}
                />
              </div>
            ))}
          </div>

          <h3 style={{ marginTop: "0.9rem", fontSize: "1rem" }}>Critical nodes JSON</h3>
          <textarea
            value={criticalNodesText}
            onChange={(e) => setCriticalNodesText(e.target.value)}
          />

          <div className="row">
            <button onClick={runAnalyze} disabled={!!busy}>
              {busy === "analyze" ? "Running analysis…" : "Run criticality"}
            </button>
          </div>
        </section>

        <section className="panel">
          <h2>Optimization (GA)</h2>
          <p className="muted">
            NSGA-II from <code>GA_WDN_Optimization.ipynb</code>. Progress streams each generation.
          </p>

          <div className="row">
            <div className="field">
              <label>Min pressure (m)</label>
              <input
                type="number"
                step="0.01"
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
                step="0.01"
                value={opt.cxpb}
                onChange={(e) => setOpt({ ...opt, cxpb: e.target.value })}
              />
            </div>
            <div className="field">
              <label>mutpb</label>
              <input
                type="number"
                step="0.01"
                value={opt.mutpb}
                onChange={(e) => setOpt({ ...opt, mutpb: e.target.value })}
              />
            </div>
            <div className="field">
              <label>indpb</label>
              <input
                type="number"
                step="0.01"
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
            <label>pipe_costs $/m (comma-separated, 2 decimals)</label>
            <input
              type="text"
              value={opt.pipe_costs}
              onChange={(e) => setOpt({ ...opt, pipe_costs: e.target.value })}
            />
          </div>
          {geometry?.optimization_defaults ? (
            <p className="muted" style={{ marginTop: "0.45rem" }}>
              Prefill from INP ({geometry.optimization_defaults.catalog}): diameters{" "}
              {geometry.optimization_defaults.diameter_min_mm}–{geometry.optimization_defaults.diameter_max_mm}{" "}
              mm → {geometry.optimization_defaults.pipe_sizes_mm.length} commercial sizes. Editable.
            </p>
          ) : (
            <p className="muted" style={{ marginTop: "0.45rem" }}>
              Upload an .inp to prefill diameters/costs from the network (Nordvik 200–1200 family when applicable).
            </p>
          )}

          <div className="row">
            <button onClick={runOptimize} disabled={!!busy}>
              {busy === "optimize" ? "Running GA…" : "Run optimization"}
            </button>
          </div>
        </section>
      </div>

      {error ? <div className="status error">{error}</div> : null}
      {busy ? (
        <div className="status">
          Working: {busy}
          {busy === "optimize" && optLive
            ? ` · gen ${optLive.generation}/${optLive.n_gen} · cost ${n2(optLive.cost)} · violation ${n2(optLive.violation)}`
            : ""}
        </div>
      ) : null}

      {(optLive || optResult) && liveHistory ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>Objective-function process</h2>
          {optLive ? (
            <p className="muted">
              Generation {optLive.generation} / {optLive.n_gen} · cost {n2(optLive.cost)} ·
              violation {n2(optLive.violation)} · Pareto size {optLive.pareto_size}
            </p>
          ) : (
            <p className="muted">Finished. Charts show best-of-Pareto (min violation) per generation.</p>
          )}
          <div className="history">
            <div>
              <small className="muted">Cost</small>
              <Sparkline values={liveHistory.cost} />
            </div>
            <div>
              <small className="muted">Violation (m)</small>
              <Sparkline values={liveHistory.violation} color="#8a4b12" />
            </div>
          </div>
          <div className="table-wrap" style={{ maxHeight: 220, marginTop: "0.75rem" }}>
            <table>
              <thead>
                <tr>
                  <th>Gen</th>
                  <th>Cost</th>
                  <th>Violation</th>
                </tr>
              </thead>
              <tbody>
                {(liveHistory.cost || []).map((c, i) => (
                  <tr key={i}>
                    <td>{i}</td>
                    <td>{n2(c)}</td>
                    <td>{n2(liveHistory.violation[i])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {analysis ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>Criticality results</h2>
          <div className="row">
            <button className="secondary" type="button" onClick={exportCriticalityCsv}>
              Download pipes CSV
            </button>
            <button className="secondary" type="button" onClick={exportBaselineCsv}>
              Download baseline CSV
            </button>
          </div>
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
              <strong>{n2(analysis.baseline.resilience_index_Ir)}</strong>
              <span>Resilience Ir</span>
            </div>
            <div className="stat">
              <strong>{n2(analysis.baseline.weighted_surplus_X)}</strong>
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
                    <td>{n2(p.Composite_Criticality)}</td>
                    <td>{p.Criticality_Class}</td>
                    <td>{n2(p["Resilience_Reduction_%"])}</td>
                    <td>{n2(p["Path_Frequency_%"])}</td>
                    <td>{n2(p["Flow_Criticality_%"])}</td>
                    <td>{n2(p["Betweenness_Centrality_%"])}</td>
                    <td>{n2(p["Demand_Coverage_%"])}</td>
                    <td>{n2(p.Segment_Importance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Showing top {topPipes.length} of {analysis.pipes.length} pipes (full set in CSV).
          </p>
        </section>
      ) : null}

      {optResult ? (
        <section className="panel" style={{ marginTop: "1rem" }}>
          <h2>Optimization results</h2>
          <div className="stats">
            <div className="stat">
              <strong>{n2(optResult.best.cost)}</strong>
              <span>Best cost</span>
            </div>
            <div className="stat">
              <strong>{n2(optResult.best.violation)}</strong>
              <span>Best violation (m)</span>
            </div>
            <div className="stat">
              <strong>{optResult.pareto_front.length}</strong>
              <span>Pareto solutions</span>
            </div>
          </div>
          <div className="row">
            <button className="secondary" type="button" onClick={exportOptCsv}>
              Download optimization CSVs
            </button>
            <button
              className="secondary"
              type="button"
              onClick={() => downloadText(`${stem}_optimized.inp`, optResult.optimized_inp || "")}
              disabled={!optResult.optimized_inp}
            >
              Download optimized .inp
            </button>
          </div>
        </section>
      ) : null}

      <footer>
        Reuses Water Criticality Code + GA_WDN_Optimization. Defaults
        {defaults ? " loaded from API." : "…"} Numerics: 2 decimals.
      </footer>
    </>
  );
}

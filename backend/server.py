"""Minimal Flask bridge: INP upload → Water Criticality Code + GA optimizer."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import criticality
import optimize

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"

app = Flask(__name__, static_folder=None)


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return resp


def _parse_json_field(form, key, default=None):
    raw = form.get(key)
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def _save_upload(file_storage) -> Path:
    if file_storage is None or not file_storage.filename:
        raise ValueError("Missing .inp file upload")
    name = Path(file_storage.filename).name
    if not name.lower().endswith(".inp"):
        raise ValueError("Upload must be an EPANET .inp file")
    tmp = Path(tempfile.mkdtemp(prefix="wdn_upload_"))
    path = tmp / name
    file_storage.save(path)
    return path


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "app": "criticality-app"})


@app.get("/api/defaults")
def defaults():
    return jsonify(
        {
            "criticality": {
                "min_head": criticality.get_min_head(),
                "composite_weights": criticality.COMPOSITE_WEIGHTS,
                "critical_nodes": {
                    k: {"structure": v[0], "importance": v[1]}
                    for k, v in criticality.CRITICAL_NODES.items()
                },
                "metrics": [
                    "Resilience_Reduction_%",
                    "Path_Frequency_%",
                    "Flow_Criticality_%",
                    "Betweenness_Centrality_%",
                    "Demand_Coverage_m3_s",
                    "Demand_Coverage_%",
                    "Segment_Importance",
                    "Composite_Criticality",
                    "Criticality_Class",
                ],
                "indexes": [
                    "weighted_surplus_X",
                    "resilience_index_Ir",
                ],
            },
            "optimization": {
                "min_pressure": 18,
                "pipe_sizes_mm": optimize.DEFAULT_PIPE_SIZES_MM,
                "pipe_costs": optimize.DEFAULT_PIPE_COSTS,
                "n_gen": 20,
                "pop_size": 30,
                "cxpb": 0.7,
                "mutpb": 0.2,
                "indpb": 0.1,
                "seed": None,
                "notebook_defaults_note": "GA_WDN_Optimization.ipynb used n_gen=500, pop_size=200",
            },
        }
    )


@app.post("/api/analyze")
def analyze():
    try:
        inp_path = _save_upload(request.files.get("file"))
        min_head = request.form.get("min_head", type=float)
        if min_head is None:
            min_head = criticality.get_min_head()

        weights = _parse_json_field(request.form, "composite_weights")
        nodes_raw = _parse_json_field(request.form, "critical_nodes")
        critical_nodes = None
        if isinstance(nodes_raw, dict):
            critical_nodes = {}
            for k, v in nodes_raw.items():
                if isinstance(v, dict):
                    critical_nodes[k] = (v.get("structure", "Critical"), float(v.get("importance", 1)))
                else:
                    critical_nodes[k] = (str(v[0]), float(v[1]))

        make_plots = request.form.get("make_plots", "false").lower() in ("1", "true", "yes")
        result = criticality.run_analysis(
            str(inp_path),
            min_head=min_head,
            critical_nodes=critical_nodes,
            composite_weights=weights,
            make_plots=make_plots,
            output_folder=str(inp_path.parent / "results") if make_plots else None,
        )
        result["source_file"] = inp_path.name
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/optimize")
def optimize_route():
    try:
        inp_path = _save_upload(request.files.get("file"))
        settings = _parse_json_field(request.form, "settings", default={}) or {}

        result = optimize.run_ga_optimization(
            str(inp_path),
            min_pressure=float(settings.get("min_pressure", 18)),
            pipe_sizes_mm=settings.get("pipe_sizes_mm"),
            pipe_costs=settings.get("pipe_costs"),
            n_gen=int(settings.get("n_gen", 20)),
            pop_size=int(settings.get("pop_size", 30)),
            cxpb=float(settings.get("cxpb", 0.7)),
            mutpb=float(settings.get("mutpb", 0.2)),
            indpb=float(settings.get("indpb", 0.1)),
            seed=settings.get("seed"),
            write_opt_inp=True,
        )
        result["source_file"] = inp_path.name
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa(path: str):
    if FRONTEND_DIST.exists():
        target = FRONTEND_DIST / path if path else FRONTEND_DIST / "index.html"
        if path and target.exists() and target.is_file():
            return send_from_directory(FRONTEND_DIST, path)
        return send_from_directory(FRONTEND_DIST, "index.html")
    return (
        "<p>Frontend not built. From <code>criticality-app/frontend</code> run "
        "<code>npm install && npm run build</code>, or use <code>npm run dev</code> "
        "with the API on port 5055.</p>",
        200,
        {"Content-Type": "text/html"},
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False)

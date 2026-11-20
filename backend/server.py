"""Minimal Flask bridge: INP upload → Water Criticality Code + GA optimizer."""

from __future__ import annotations

import json
import queue
import tempfile
import threading
from pathlib import Path

import wntr
from flask import Flask, Response, jsonify, request, send_from_directory

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


def _network_geometry(inp_path: Path) -> dict:
    """Nodes + pipes with EPANET coordinates for the React figure."""
    wn = wntr.network.WaterNetworkModel(str(inp_path))
    nodes = []
    for name in wn.node_name_list:
        node = wn.get_node(name)
        x, y = node.coordinates if node.coordinates is not None else (0.0, 0.0)
        nodes.append(
            {
                "id": str(name),
                "x": round(float(x), 2),
                "y": round(float(y), 2),
                "type": str(node.node_type),
            }
        )
    pipes = []
    for name in wn.pipe_name_list:
        link = wn.get_link(name)
        pipes.append(
            {
                "id": str(name),
                "start": str(link.start_node_name),
                "end": str(link.end_node_name),
                "diameter_m": round(float(link.diameter), 2),
                "length_m": round(float(link.length), 2),
            }
        )
    return {
        "source_file": inp_path.name,
        "nodes": nodes,
        "pipes": pipes,
        "counts": {
            "nodes": len(nodes),
            "pipes": len(pipes),
            "junctions": len(wn.junction_name_list),
            "reservoirs": len(wn.reservoir_name_list),
            "tanks": len(wn.tank_name_list),
        },
    }


def _opt_kwargs(settings: dict) -> dict:
    return dict(
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


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "app": "criticality-app"})


@app.get("/api/defaults")
def defaults():
    return jsonify(
        {
            "criticality": {
                "min_head": round(float(criticality.get_min_head()), 2),
                "composite_weights": {
                    k: round(float(v), 2) for k, v in criticality.COMPOSITE_WEIGHTS.items()
                },
                "critical_nodes": {
                    k: {"structure": v[0], "importance": round(float(v[1]), 2)}
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
                "numeric_decimals": 2,
            },
            "optimization": {
                "min_pressure": 18.0,
                "pipe_sizes_mm": [float(v) for v in optimize.DEFAULT_PIPE_SIZES_MM],
                "pipe_costs": [float(v) for v in optimize.DEFAULT_PIPE_COSTS],
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


@app.post("/api/network")
def network():
    try:
        inp_path = _save_upload(request.files.get("file"))
        return jsonify(_network_geometry(inp_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


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
        result["geometry"] = _network_geometry(inp_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/optimize")
def optimize_route():
    try:
        inp_path = _save_upload(request.files.get("file"))
        settings = _parse_json_field(request.form, "settings", default={}) or {}
        result = optimize.run_ga_optimization(str(inp_path), **_opt_kwargs(settings))
        result["source_file"] = inp_path.name
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/optimize/stream")
def optimize_stream():
    """NDJSON stream: progress lines, then a final done/error line."""
    try:
        inp_path = _save_upload(request.files.get("file"))
        settings = _parse_json_field(request.form, "settings", default={}) or {}
        kwargs = _opt_kwargs(settings)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    def generate():
        q: queue.Queue = queue.Queue()

        def on_generation(payload):
            q.put(("progress", payload))

        def worker():
            try:
                result = optimize.run_ga_optimization(
                    str(inp_path), on_generation=on_generation, **kwargs
                )
                result["source_file"] = inp_path.name
                q.put(("done", result))
            except Exception as exc:
                q.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, data = q.get()
            if kind == "progress":
                yield json.dumps({"event": "progress", **data}) + "\n"
            elif kind == "done":
                yield json.dumps({"event": "done", "result": data}) + "\n"
                break
            else:
                yield json.dumps({"event": "error", "error": data}) + "\n"
                break

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    app.run(host="127.0.0.1", port=5055, debug=False, threaded=True)

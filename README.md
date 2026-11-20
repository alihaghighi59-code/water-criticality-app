# WDN Criticality App (Ali Haghighi)

Minimal React + Flask app under `Roya/criticality-app`.

- **Criticality**: reuses logic from `Water Criticality Code/WDN_Criticality.ipynb` (`backend/criticality.py`).
- **Optimization**: reuses the DEAP NSGA-II pipe-sizing GA from `GA_WDN_Optimization.ipynb` (`backend/optimize.py`).

## Run (double-click)

Double-click **`Start Criticality App.bat`** in this folder. It starts the API (5055), the Vite UI (5173), installs frontend deps if needed, and opens the browser. Leave the two server windows open.

### Manual

### 1. API (Python)

```powershell
cd C:\Users\Administrator\Desktop\Roya\criticality-app
py -3 -m pip install -r requirements.txt
cd backend
py -3 server.py
```

API: http://127.0.0.1:5055

### 2. UI (React / Vite)

```powershell
cd C:\Users\Administrator\Desktop\Roya\criticality-app\frontend
npm install
npm run dev
```

UI: http://127.0.0.1:5173 (proxies `/api` to the Flask server)

Optional: `npm run build` then open the Flask server — it serves `frontend/dist`.

## UI additions

- **Network figure:** Opus-style Leaflet map (`CRS.Simple`, dark water bg, conduit/junction colors, Labels Auto|All|Off, pipe/node name tooltips) via `/api/network`; pipes tint by composite after analysis.
- **CSV export:** criticality pipes + baseline; optimization history / Pareto / diameters / best.
- **Live GA progress:** `/api/optimize/stream` (NDJSON) updates cost/violation charts and table each generation. **Stop** (`POST /api/optimize/stop`) halts after the current generation and keeps best-so-far (CSV + optimized `.inp`).
- **Help tab:** formulations for indices and GA objectives from the notebooks.
- **Decimals:** all floating results display/export with **two decimal places**.

## Metrics / indexes (criticality)

Per pipe:

- Resilience_Reduction_%
- Path_Frequency_%
- Flow_Criticality_%
- Betweenness_Centrality_%
- Demand_Coverage_m3_s / Demand_Coverage_%
- Segment_Importance
- Composite_Criticality (+ Criticality_Class)

Network indexes:

- weighted surplus **X**
- resilience index **Ir**

Settings: min head Hl, composite weights, critical-node importance map.

## Optimization settings (GA)

- min_pressure
- pipe_sizes_mm, pipe_costs — **auto-filled on INP upload**. Nordvik → exact inventory  
  `200,203,206,225,229,250,254,280,300,305,315,324,350,355,356,381,400,450,483,500,533,560,584,600,610,630,700,710,800,900,1000,1200`  
  with matching `$/m` costs (2 decimals). Other networks → diameters present in the INP.
- n_gen, pop_size
- cxpb, mutpb, indpb
- seed (optional)

Objectives: minimize total pipe cost and average pressure violation (NSGA-II).

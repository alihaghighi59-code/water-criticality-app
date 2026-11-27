# Water Criticality App – Clone & Run

Web app for water distribution network (WDN) pipe criticality analysis and NSGA-II pipe-sizing optimization. Flask API (Python) + React/Vite UI. You bring your own EPANET `.inp` file.

## 1. Prerequisites

- **Git**
- **Python 3.9+** (3.10–3.12 recommended)
- **Node.js 18+** (includes `npm`)

## 2. Get the code

```bash
git clone https://github.com/alihaghighi59-code/water-criticality-app.git
cd water-criticality-app
```

## 3. Install dependencies (once)

```bash
# Python (Windows: use `py -3` instead of `python`)
python -m pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

## 4. Run

Open **two terminals** in the repo folder.

**Terminal 1 – API (port 5055)**

```bash
cd backend
python server.py        # Windows: py -3 server.py
```

**Terminal 2 – UI (port 5173)**

```bash
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173** in your browser.

**Windows shortcut:** double-click `Start Criticality App.bat` – it installs frontend deps if missing, starts both servers and opens the browser. Keep both server windows open.

## 5. Use the app

1. Upload an EPANET network (`.inp`).
2. **Criticality tab:** tick the metrics you want (resilience reduction is the slowest – one EPANET run per pipe), set min head and composite weights, run. Export results as CSV.
3. **Optimization tab:** set min pressure, pipe diameters/costs (auto-filled from the INP), generations, population, GA probabilities, optional seed. Run, watch live progress, press **Stop** to keep best-so-far, export CSV or the optimized `.inp`.
4. **Help tab:** formulas for all indices and objectives.

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| UI loads but analysis fails | Make sure the API terminal is running on port 5055. |
| Port already in use | Close the old server window, or stop whatever uses 5055 / 5173. |
| `pip` install of `wntr`/`deap` fails | Upgrade pip (`python -m pip install -U pip`) and use a 64-bit Python. |
| `py` / `npm` not found (Windows) | Install Python / Node.js and reopen the terminal. |

Quick self-check of the metric logic: `python backend/check_metrics.py`

More detail on metrics and GA settings: see `README.md`.

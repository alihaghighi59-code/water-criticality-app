"""Self-check: unchecked metrics are skipped; shared metrics match the full run. Run: py -3 check_metrics.py"""
import sys
from pathlib import Path

import criticality as c

inp = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2] / "WDN_Bagh" / "Bagh_Modified.inp")
fast = c.run_analysis(inp, metrics=["path_frequency", "flow", "betweenness", "demand", "composite"])
full = c.run_analysis(inp)
assert "Resilience_Reduction_%" not in fast["columns"] and "Segment_Importance" not in fast["columns"]
assert fast["baseline"]["resilience_index_Ir"] is None and full["baseline"]["resilience_index_Ir"] is not None
f = {p["Pipe_ID"]: p for p in fast["pipes"]}
a = {p["Pipe_ID"]: p for p in full["pipes"]}
for k in ("Path_Frequency_%", "Flow_Criticality_%", "Betweenness_Centrality_%", "Demand_Coverage_%"):
    assert all(f[i][k] == a[i][k] for i in f), k
print("OK")

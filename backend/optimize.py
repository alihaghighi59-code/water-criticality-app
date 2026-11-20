"""Pipe-sizing GA from Roya/GA_WDN_Optimization.ipynb — settings exposed, logic unchanged."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import wntr
from deap import algorithms, base, creator, tools

# UI / API default discrete sizes = exact Nordvik inventory (see NORDVIK_INVENTORY_MM).
# Costs filled after UNIT_COST_BY_MM is defined (see below).

# Exact Nordvik discrete inventory (mm) — do not round/replace with a coarser family.
NORDVIK_INVENTORY_MM = [
    200, 203, 206, 225, 229, 250, 254, 280, 300, 305, 315, 324,
    350, 355, 356, 381, 400, 450, 483, 500, 533, 560, 584, 600,
    610, 630, 700, 710, 800, 900, 1000, 1200,
]
# Back-compat alias
NORDVIK_FAMILY_MM = NORDVIK_INVENTORY_MM

# Master catalog for non-Nordvik snapping (mm).
COMMERCIAL_MM = sorted(set(
    [100, 110, 130, 150] + NORDVIK_INVENTORY_MM
))

# Unit cost $/m — GA notebook anchors + explicit Nordvik inventory (always 2 dp).
UNIT_COST_BY_MM = {
    100: 50.00,
    110: 55.00,
    130: 65.00,
    150: 75.00,
    200: 90.00,
    203: 91.20,
    206: 92.40,
    225: 100.00,
    229: 102.40,
    250: 115.00,
    254: 117.00,
    280: 130.00,
    300: 140.00,
    305: 143.33,
    315: 150.00,
    324: 153.86,
    350: 165.00,
    355: 170.00,
    356: 170.89,
    381: 193.11,
    400: 210.00,
    450: 255.00,
    483: 321.00,
    500: 355.00,
    533: 374.25,
    560: 390.00,
    584: 414.00,
    600: 430.00,
    610: 440.00,
    630: 460.00,
    700: 650.00,
    710: 663.00,
    800: 780.00,
    900: 920.00,
    1000: 1100.00,
    1200: 1450.00,
}

DEFAULT_PIPE_SIZES_MM = list(NORDVIK_INVENTORY_MM)
DEFAULT_PIPE_COSTS = [round(float(UNIT_COST_BY_MM[d]), 2) for d in NORDVIK_INVENTORY_MM]


def _r2(x):
    return round(float(x), 2)


def unit_cost_for_mm(diameter_mm: float) -> float:
    """Lookup or linearly interpolate unit cost ($/m) at two decimals."""
    d = float(diameter_mm)
    if d in UNIT_COST_BY_MM:
        return _r2(UNIT_COST_BY_MM[d])
    keys = sorted(UNIT_COST_BY_MM)
    if d <= keys[0]:
        return _r2(UNIT_COST_BY_MM[keys[0]])
    if d >= keys[-1]:
        # mild extrapolation beyond 1200 mm
        k0, k1 = keys[-2], keys[-1]
        c0, c1 = UNIT_COST_BY_MM[k0], UNIT_COST_BY_MM[k1]
        slope = (c1 - c0) / (k1 - k0)
        return _r2(c1 + slope * (d - k1))
    for i in range(len(keys) - 1):
        a, b = keys[i], keys[i + 1]
        if a <= d <= b:
            ca, cb = UNIT_COST_BY_MM[a], UNIT_COST_BY_MM[b]
            t = (d - a) / (b - a) if b != a else 0.0
            return _r2(ca + t * (cb - ca))
    return _r2(UNIT_COST_BY_MM[keys[-1]])


def _nearest_commercial(mm: float, catalog: list[int]) -> int:
    return min(catalog, key=lambda c: abs(c - mm))


def diameters_and_costs_from_network(inp_path) -> dict:
    """Build default GA pipe_sizes_mm / pipe_costs from diameters in the INP.

    - Reads unique pipe diameters (mm) from the model.
    - If the network spans the Nordvik family (~200–1200 mm), uses NORDVIK_FAMILY_MM
      clipped to the observed min/max (with nearest commercial edges).
    - Otherwise uses commercial catalog sizes covering the observed range, plus
      nearest snaps of diameters actually present.
    """
    wn = wntr.network.WaterNetworkModel(str(inp_path))
    present_mm = sorted(
        {
            int(round(float(wn.get_link(name).diameter) * 1000.0))
            for name in wn.pipe_name_list
        }
    )
    if not present_mm:
        sizes = list(DEFAULT_PIPE_SIZES_MM)
        costs = [_r2(c) for c in DEFAULT_PIPE_COSTS]
        return {
            "pipe_sizes_mm": sizes,
            "pipe_costs": costs,
            "present_mm": [],
            "catalog": "fallback_notebook",
            "cost_table": {str(s): _r2(c) for s, c in zip(sizes, costs)},
        }

    d_min, d_max = present_mm[0], present_mm[-1]
    # Nordvik-like → exact inventory set (no rounding to a coarser family)
    nordvik_like = d_min >= 180 and d_max >= 900
    if nordvik_like or set(present_mm) >= set(NORDVIK_INVENTORY_MM):
        sizes = list(NORDVIK_INVENTORY_MM)
        catalog_name = "nordvik_inventory_exact"
    else:
        # Diameters actually present in the INP, snapped to nearest commercial size
        catalog = COMMERCIAL_MM
        sizes = sorted({_nearest_commercial(p, catalog) for p in present_mm})
        catalog_name = "present_in_inp"

    costs = [unit_cost_for_mm(s) for s in sizes]
    return {
        "pipe_sizes_mm": sizes,
        "pipe_costs": costs,
        "present_mm": present_mm,
        "diameter_min_mm": d_min,
        "diameter_max_mm": d_max,
        "catalog": catalog_name,
        "cost_table": {str(s): c for s, c in zip(sizes, costs)},
    }


def _reset_deap_creators():
    if hasattr(creator, "FitnessMulti"):
        del creator.FitnessMulti
    if hasattr(creator, "Individual"):
        del creator.Individual


def run_ga_optimization(
    inp_path,
    *,
    min_pressure=18.0,
    pipe_sizes_mm=None,
    pipe_costs=None,
    n_gen=20,
    pop_size=30,
    cxpb=0.7,
    mutpb=0.2,
    indpb=0.1,
    seed=None,
    write_opt_inp=True,
    on_generation=None,
    should_stop=None,
):
    """NSGA-II multi-objective pipe sizing (cost + pressure violation).

    Defaults for n_gen/pop_size are UI-safe; notebook used n_gen=500, pop_size=200.
    on_generation(payload): optional callback each generation (incl. gen 0 = initial pop).
    should_stop(): optional; when True between generations, halt and return best-so-far.
    """
    pipe_sizes = np.array(pipe_sizes_mm if pipe_sizes_mm is not None else DEFAULT_PIPE_SIZES_MM, dtype=float)
    pipe_costs = np.array(pipe_costs if pipe_costs is not None else DEFAULT_PIPE_COSTS, dtype=float)
    if len(pipe_sizes) != len(pipe_costs):
        raise ValueError("pipe_sizes_mm and pipe_costs must have the same length")
    if len(pipe_sizes) < 1:
        raise ValueError("Need at least one commercial pipe size")

    if seed is not None:
        np.random.seed(int(seed))

    wn = wntr.network.WaterNetworkModel(str(inp_path))
    pipes = list(wn.pipe_name_list)
    n_pipes = len(pipes)
    if n_pipes == 0:
        raise ValueError("Network has no pipes")

    reservoir_nodes = [
        name for name in wn.node_name_list if wn.get_node(name).node_type == "Reservoir"
    ]

    _reset_deap_creators()
    creator.create("FitnessMulti", base.Fitness, weights=(-1.0, -1.0))
    creator.create("Individual", list, fitness=creator.FitnessMulti)

    toolbox = base.Toolbox()
    toolbox.register("attr_int", np.random.randint, 0, len(pipe_sizes))
    toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.attr_int, n_pipes)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    def evaluate(individual):
        try:
            for i, pipe_idx in enumerate(individual):
                wn.get_link(pipes[i]).diameter = float(pipe_sizes[int(pipe_idx)]) / 1000.0
            sim = wntr.sim.EpanetSimulator(wn)
            results = sim.run_sim()
            pressures = results.node["pressure"].loc[0]
        except Exception:
            return 1e9, 1e3

        non_reservoir_nodes = [node for node in pressures.index if node not in reservoir_nodes]
        violation = sum(max(0.0, float(min_pressure) - float(pressures[node])) for node in non_reservoir_nodes)
        violation = violation / len(non_reservoir_nodes) if non_reservoir_nodes else 0.0

        cost = 0.0
        for i, pipe_idx in enumerate(individual):
            length = float(wn.get_link(pipes[i]).length)
            cost += length * float(pipe_costs[int(pipe_idx)])
        return cost, violation

    toolbox.register("evaluate", evaluate)
    toolbox.register("mate", tools.cxTwoPoint)
    toolbox.register(
        "mutate",
        tools.mutUniformInt,
        low=0,
        up=len(pipe_sizes) - 1,
        indpb=float(indpb),
    )
    toolbox.register("select", tools.selNSGA2)

    pop = toolbox.population(n=int(pop_size))
    hof = tools.ParetoFront()
    cost_history = []
    violation_history = []

    def _emit(generation, best_ind):
        payload = {
            "generation": int(generation),
            "n_gen": int(n_gen),
            "cost": _r2(best_ind.fitness.values[0]),
            "violation": _r2(best_ind.fitness.values[1]),
            "cost_history": [_r2(v) for v in cost_history],
            "violation_history": [_r2(v) for v in violation_history],
            "pareto_size": len(hof),
        }
        if on_generation is not None:
            on_generation(payload)

    def _stop_requested():
        try:
            return bool(should_stop and should_stop())
        except Exception:
            return False

    stopped_early = False
    last_gen = 0

    fits = toolbox.map(toolbox.evaluate, pop)
    for ind, fit in zip(pop, fits):
        ind.fitness.values = fit
    hof.update(pop)
    best0 = min(hof, key=lambda ind: ind.fitness.values[1])
    cost_history.append(float(best0.fitness.values[0]))
    violation_history.append(float(best0.fitness.values[1]))
    _emit(0, best0)

    if _stop_requested():
        stopped_early = True
    else:
        for gen in range(1, int(n_gen) + 1):
            if _stop_requested():
                stopped_early = True
                break
            offspring = algorithms.varAnd(pop, toolbox, cxpb=float(cxpb), mutpb=float(mutpb))
            fits = toolbox.map(toolbox.evaluate, offspring)
            for ind, fit in zip(offspring, fits):
                ind.fitness.values = fit
            pop = toolbox.select(offspring + pop, k=int(pop_size))
            hof.update(pop)
            best = min(hof, key=lambda ind: ind.fitness.values[1])
            cost_history.append(float(best.fitness.values[0]))
            violation_history.append(float(best.fitness.values[1]))
            last_gen = gen
            _emit(gen, best)
            if _stop_requested():
                stopped_early = True
                break

    best_solution = min(hof, key=lambda ind: (ind.fitness.values[1], ind.fitness.values[0]))
    for i, pipe_idx in enumerate(best_solution):
        wn.get_link(pipes[i]).diameter = float(pipe_sizes[int(pipe_idx)]) / 1000.0

    opt_inp_text = None
    opt_inp_path = None
    if write_opt_inp:
        tmp = Path(tempfile.mkdtemp(prefix="wdn_opt_"))
        opt_inp_path = tmp / "optimized.inp"
        wntr.network.write_inpfile(wn, str(opt_inp_path))
        opt_inp_text = opt_inp_path.read_text(encoding="utf-8", errors="replace")

    diameter_mm = {
        pipes[i]: _r2(pipe_sizes[int(pipe_idx)]) for i, pipe_idx in enumerate(best_solution)
    }

    return {
        "n_pipes": n_pipes,
        "stopped_early": bool(stopped_early),
        "generations_completed": int(last_gen if last_gen or stopped_early else int(n_gen)),
        "settings": {
            "min_pressure": _r2(min_pressure),
            "pipe_sizes_mm": [_r2(v) for v in pipe_sizes.tolist()],
            "pipe_costs": [_r2(v) for v in pipe_costs.tolist()],
            "n_gen": int(n_gen),
            "pop_size": int(pop_size),
            "cxpb": _r2(cxpb),
            "mutpb": _r2(mutpb),
            "indpb": _r2(indpb),
            "seed": seed,
        },
        "best": {
            "cost": _r2(best_solution.fitness.values[0]),
            "violation": _r2(best_solution.fitness.values[1]),
            "pipe_diameters_mm": diameter_mm,
        },
        "pareto_front": [
            {"cost": _r2(ind.fitness.values[0]), "violation": _r2(ind.fitness.values[1])}
            for ind in hof
        ],
        "history": {
            "cost": [_r2(v) for v in cost_history],
            "violation": [_r2(v) for v in violation_history],
        },
        "optimized_inp": opt_inp_text,
        "optimized_inp_path": str(opt_inp_path) if opt_inp_path else None,
    }

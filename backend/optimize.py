"""Pipe-sizing GA from Roya/GA_WDN_Optimization.ipynb — settings exposed, logic unchanged."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import wntr
from deap import algorithms, base, creator, tools

DEFAULT_PIPE_SIZES_MM = [100, 200, 300, 400, 500, 600, 700]
DEFAULT_PIPE_COSTS = [50, 90, 140, 210, 355, 430, 650]


def _r2(x):
    return round(float(x), 2)


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
):
    """NSGA-II multi-objective pipe sizing (cost + pressure violation).

    Defaults for n_gen/pop_size are UI-safe; notebook used n_gen=500, pop_size=200.
    on_generation(payload): optional callback each generation (incl. gen 0 = initial pop).
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

    fits = toolbox.map(toolbox.evaluate, pop)
    for ind, fit in zip(pop, fits):
        ind.fitness.values = fit
    hof.update(pop)
    best0 = min(hof, key=lambda ind: ind.fitness.values[1])
    cost_history.append(float(best0.fitness.values[0]))
    violation_history.append(float(best0.fitness.values[1]))
    _emit(0, best0)

    for gen in range(1, int(n_gen) + 1):
        offspring = algorithms.varAnd(pop, toolbox, cxpb=float(cxpb), mutpb=float(mutpb))
        fits = toolbox.map(toolbox.evaluate, offspring)
        for ind, fit in zip(offspring, fits):
            ind.fitness.values = fit
        pop = toolbox.select(offspring + pop, k=int(pop_size))
        hof.update(pop)
        best = min(hof, key=lambda ind: ind.fitness.values[1])
        cost_history.append(float(best.fitness.values[0]))
        violation_history.append(float(best.fitness.values[1]))
        _emit(gen, best)

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

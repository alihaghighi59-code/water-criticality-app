/** Formulations from Water Criticality Code + GA_WDN_Optimization notebooks. */

export default function Help() {
  return (
    <article className="help">
      <h2>Help — ideas and formulations</h2>
      <p className="muted">
        This page documents the measures and objective functions implemented in the Water Criticality
        Code (<code>WDN_Criticality.ipynb</code>) and the pipe-sizing GA (<code>GA_WDN_Optimization.ipynb</code>).
        Numeric results in the app are shown and exported with two decimal places.
      </p>

      <h3>1. Node importance I<sub>j</sub></h3>
      <p>
        Critical infrastructures at junctions are user-defined as{" "}
        <code>node → (structure name, importance factor)</code>. Every junction starts at{" "}
        <code>I<sub>j</sub> = 1.00</code>; listed critical nodes override that factor (e.g. hospital 4,
        fire station 6). Importance propagates into surplus, path frequency, flow, betweenness, and
        demand coverage.
      </p>

      <h3>2. Uniformity coefficient C<sub>j</sub></h3>
      <p>
        For junction <em>j</em> with incident pipe diameters D<sub>i</sub> (np<sub>j</sub> pipes):
      </p>
      <pre>{`Cj = 1                          if npj ≤ 1
Cj = Σ Di / (npj · max(Di))     otherwise`}</pre>

      <h3>3. Network weighted surplus X and resilience index I<sub>r</sub></h3>
      <p>
        With minimum required head H<sub>l</sub> (default 18.00 m), demand Q<sub>j</sub>, and head
        H<sub>j</sub> from the baseline EPANET run:
      </p>
      <pre>{`X = Σ_j  Ij · Cj · Qj · max(Hj − Hl, 0)

Ir = X / Σ_j  Ij · Qj · (Hs − Hl)`}</pre>
      <p>
        H<sub>s</sub> is the mean reservoir head. Pipe <strong>resilience reduction (%)</strong> closes
        one pipe (or treats reservoir-connected pipes as 100.00%) and measures the drop in X:
      </p>
      <pre>{`ΔIr% = 100 · (X_baseline − X_without_pipe) / X_baseline
       (clipped to [0, 100]; fallback uses importance-weighted flow share)`}</pre>

      <h3>4. Path frequency (PF %)</h3>
      <p>
        Shortest paths on the undirected pipe graph from each junction toward supply. Each junction
        contributes its importance I<sub>j</sub> to pipes used on those paths; scores are normalized
        to a percentage of the maximum (importance-weighted path usage).
      </p>

      <h3>5. Flow criticality (%)</h3>
      <pre>{`Ip = 0.5 · (Iu + Iv)     for pipe endpoints u, v
flow_crit% = 100 · ( |Q_pipe| · Ip ) / max_pipe( |Q| · Ip )`}</pre>

      <h3>6. Betweenness centrality (%)</h3>
      <p>
        NetworkX edge betweenness (normalized) on the undirected pipe graph, then scaled by the
        average endpoint importance I<sub>u</sub>, I<sub>v</sub> and expressed as a percentage of the
        maximum among pipes.
      </p>

      <h3>7. Demand coverage</h3>
      <p>
        Importance-weighted demand associated with the pipe’s local segment / connected junctions
        (absolute base demands × I<sub>j</sub>), reported as m³/s and as % of total network
        importance-weighted demand.
      </p>

      <h3>8. Segment importance</h3>
      <p>
        Hydraulic/geometric segment score from the criticality notebook (length/diameter/flow
        context of the pipe segment), reported alongside the other metrics.
      </p>

      <h3>9. Composite criticality and classes</h3>
      <p>Default weights (editable in the UI; must be consistent with the notebook source of truth):</p>
      <pre>{`Composite =
  0.35 · Resilience_Reduction_%
+ 0.35 · Path_Frequency_%
+ 0.15 · Flow_Criticality_%
+ 0.10 · Betweenness_Centrality_%
+ 0.05 · Demand_Coverage_%

Classes: Critical ≥ 75 | High ≥ 50 | Medium ≥ 25 | Low < 25`}</pre>
      <p>
        If some metrics are unchecked, they are not computed and the composite uses only the
        checked weighted components, with weights rescaled by (sum of all weights) / (sum of used
        weights) so it stays on the same 0–100 scale.
      </p>

      <h3>10. Optimization objectives (GA / NSGA-II)</h3>
      <p>
        From <code>GA_WDN_Optimization.ipynb</code>: discrete commercial diameters for every pipe;
        DEAP NSGA-II with fitness weights <code>(−1, −1)</code> (minimize both):
      </p>
      <pre>{`Cost = Σ_pipes  length_p · unit_cost(diameter_index_p)

Violation = (1/N) · Σ_nodes max(0, Pmin − P_node)
            (non-reservoir nodes; Pmin default 18.00 m)`}</pre>
      <p>
        Operators: two-point crossover (<code>cxpb</code>), uniform-integer mutation (
        <code>mutpb</code>, per-gene <code>indpb</code>), NSGA-II selection. Failed hydraulics return
        large penalties (1e9, 1e3). The UI streams cost and violation each generation (generation 0 =
        initial population).
      </p>

      <h3>11. Display / CSV rule</h3>
      <p>
        All floating-point results (tables, chart labels, CSV exports, API metrics) use{" "}
        <strong>two decimal places</strong>. Discrete counts (rank, generation index, pipe counts)
        stay as integers.
      </p>
    </article>
  );
}

import wntr
import pandas as pd
import os
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D
import logging
import traceback
from pathlib import Path
import numpy as np
from copy import deepcopy
import seaborn as sns
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ============================================================
#  Critical node importance (user-defined)
# ============================================================

# Dictionary of critical infrastructures at nodes.
# Format: node_name: (structure_name, importance_factor)
CRITICAL_NODES = {
    '16': ('Hospital', 4),
    '24': ('Hotel', 2),
    '65': ('Day care', 2),
    '25': ('School', 4),
    '74': ('School', 4),
    '43': ('Train station', 2),
    '32': ('Fire station', 6),
}

# Plotting style per structure type (marker + color)
STRUCTURE_STYLES = {
    'Hospital':      dict(marker='D', color='red'),      # red diamond
    'School':        dict(marker='o', color='green'),    # green circle
    'Fire station':  dict(marker='s', color='orange'),   # orange square
    'Train station': dict(marker='^', color='purple'),   # purple triangle
    'Hotel':         dict(marker='P', color='brown'),    # brown plus-filled
    'Day care':      dict(marker='X', color='magenta'),  # magenta X
}

# ============================================================
#  Composite criticality weights (single source of truth)
# ============================================================
COMPOSITE_WEIGHTS = {
    'Resilience_Reduction_%':   0.35,
    'Path_Frequency_%':         0.35,
    'Flow_Criticality_%':       0.15,
    'Betweenness_Centrality_%': 0.10,
    'Demand_Coverage_%':        0.05,
}


def get_node_importance(wn):
    """Return dict node_name -> importance factor (>=1 for critical nodes, 1.0 by default)."""
    # Start with 1.0 for all junctions
    node_importance = {str(name): 1.0 for name in wn.junction_name_list}

    # Override with user-defined critical nodes (if they exist in the network)
    for raw_name, (_, factor) in CRITICAL_NODES.items():
        name = str(raw_name)
        if name in node_importance:
            try:
                node_importance[name] = float(factor)
            except Exception:
                node_importance[name] = 1.0

    return node_importance


# Setup logging
def setup_logging(output_folder):
    """Setup logging to file in the output folder."""
    log_file = output_folder / 'analysis.log'
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filemode='w'
    )
    # Also log to console
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger('').addHandler(console)

def get_min_head():
    """Get minimum pressure head (default 18.0 meters)."""
    return 18.0


# ============================================================
#  Compute uniformity coefficient and network surplus (Eq. 15)
# ============================================================

def compute_uniformity_coeff_for_node(wn, node_name):
    """Compute Cj = ΣDi / (npj * max(Di)), or 1 if npj == 1."""
    try:
        link_names = wn.get_links_for_node(node_name)
    except Exception:
        link_names = []
    diameters = []
    for link_name in link_names:
        try:
            link = wn.get_link(link_name)
            if hasattr(link, "diameter"):
                d = float(link.diameter)
                if d > 0:
                    diameters.append(d)
        except Exception:
            continue
    npj = len(diameters)
    if npj <= 1:
        return 1.0
    Dmax = max(diameters)
    if Dmax <= 0:
        return 1.0
    return sum(diameters) / (npj * Dmax)


def compute_network_surplus(wn, results, min_head, node_importance=None):
    """Compute network weighted surplus X = Σ Ij * Cj * Qj * (Hj - Hl).

    node_importance: dict mapping node_name -> importance factor (Ij), default 1.0.
    """
    if node_importance is None:
        node_importance = {}

    node_head = results.node["head"]
    node_demand = results.node["demand"]

    X = 0.0
    node_info = {}

    for node_name in wn.junction_name_list:
        try:
            Qj = float(node_demand.loc[:, node_name].mean())
            Hj = float(node_head.loc[:, node_name].mean())
        except Exception:
            Qj = 0.0
            Hj = 0.0

        Cj = compute_uniformity_coeff_for_node(wn, node_name)
        surplus_head = max(Hj - min_head, 0.0)
        Ij = float(node_importance.get(str(node_name), 1.0))
        contrib = Ij * Cj * Qj * surplus_head
        X += contrib
        node_info[node_name] = {
            "Cj": Cj,
            "Qj": Qj,
            "Hj": Hj,
            "surplus_head": surplus_head,
            "importance": Ij,
            "contribution": contrib,
        }

    return X, node_info


# ============================================================
#  NEW: Additional Criticality Metrics
# ============================================================

def compute_flow_based_criticality(baseline_flows, pipe_name, max_flow, pipe_importance=None):
    """Flow-based criticality: normalized importance-weighted flow rate.

    pipe_importance: optional dict mapping pipe_id -> importance factor (>=1 for
    pipes connected to critical nodes, 1.0 otherwise).
    """
    if pipe_importance is None:
        pipe_importance = {}

    base_flow = baseline_flows.get(pipe_name, 0.0)
    Ip = float(pipe_importance.get(pipe_name, 1.0))
    flow = base_flow * Ip
    return (flow / max_flow) * 100 if max_flow > 0 else 0.0


def compute_betweenness_centrality(wn, node_importance=None):
    """Compute edge betweenness centrality for all pipes and weight by node importance.

    The raw topological edge betweenness is multiplied by the average importance
    of the two endpoint nodes of each pipe.
    """
    if node_importance is None:
        node_importance = {}

    G = nx.Graph()
    for node_name in wn.node_name_list:
        G.add_node(node_name)
    
    pipe_to_edge = {}
    for pipe_name in wn.pipe_name_list:
        pipe = wn.get_link(pipe_name)
        G.add_edge(pipe.start_node_name, pipe.end_node_name, pipe_id=pipe_name)
        pipe_to_edge[pipe_name] = (pipe.start_node_name, pipe.end_node_name)
    
    edge_betweenness = nx.edge_betweenness_centrality(G, normalized=True)
    
    pipe_betweenness = {}
    for pipe_name, (u, v) in pipe_to_edge.items():
        # Edge betweenness is stored for unordered pairs
        bc = edge_betweenness.get((u, v), edge_betweenness.get((v, u), 0.0))
        Iu = float(node_importance.get(str(u), 1.0))
        Iv = float(node_importance.get(str(v), 1.0))
        importance_factor = 0.5 * (Iu + Iv)
        pipe_betweenness[pipe_name] = bc * importance_factor * 100  # percentage
    
    return pipe_betweenness


def compute_demand_coverage(wn, pipe_name, node_importance=None):
    """Compute total demand served downstream of pipe, weighted by node importance."""
    if node_importance is None:
        node_importance = {}

    G = nx.DiGraph()
    for node_name in wn.node_name_list:
        G.add_node(node_name)
    
    for p_name in wn.pipe_name_list:
        pipe = wn.get_link(p_name)
        G.add_edge(pipe.start_node_name, pipe.end_node_name, pipe_id=p_name)
    
    pipe = wn.get_link(pipe_name)
    start_node = pipe.start_node_name
    end_node = pipe.end_node_name
    
    # Find all nodes reachable from end_node (downstream)
    try:
        downstream_nodes = nx.descendants(G, end_node)
        downstream_nodes.add(end_node)
    except:
        downstream_nodes = {end_node}
    
    # Sum importance-weighted demands
    total_demand = 0.0
    for node in downstream_nodes:
        if node in wn.junction_name_list:
            junction = wn.get_node(node)
            base_demand = getattr(junction, 'base_demand', 0.0)
            if base_demand is None:
                base_demand = 0.0
            Ij = float(node_importance.get(str(node), 1.0))
            total_demand += abs(float(base_demand)) * Ij
    
    return total_demand


def compute_segment_importance(wn, pipe_name, baseline_results):
    """Compute importance based on velocity and demand."""
    try:
        velocity = abs(baseline_results.link['velocity'].loc[:, pipe_name].mean())
        pipe = wn.get_link(pipe_name)
        diameter = float(pipe.diameter)
        length = float(pipe.length)
        
        # Importance combines velocity, diameter, and length
        importance = velocity * diameter * length
        return importance
    except:
        return 0.0


# ============================================================
#  Reservoir, path frequency functions
# ============================================================

def identify_reservoir_pipes(wn):
    """Identify pipes directly connected to reservoirs."""
    reservoir_pipes = set()
    for reservoir_name in wn.reservoir_name_list:
        connected_links = wn.get_links_for_node(reservoir_name)
        for link_name in connected_links:
            if link_name in wn.pipe_name_list:
                reservoir_pipes.add(link_name)
    return list(reservoir_pipes)


def compute_path_frequency(wn, node_importance=None):
    """Compute frequency of each pipe in shortest paths to reservoir, weighted by node importance.

    Each junction contributes its importance factor Ij to paths that originate
    from it, so pipes serving more important junctions appear more frequently.
    """
    if node_importance is None:
        node_importance = {}

    G = nx.Graph()
    for node_name in wn.node_name_list:
        G.add_node(node_name)
    for pipe_name in wn.pipe_name_list:
        pipe = wn.get_link(pipe_name)
        G.add_edge(pipe.start_node_name, pipe.end_node_name, pipe_id=pipe_name)

    if not wn.reservoir_name_list:
        return {pipe: 0.0 for pipe in wn.pipe_name_list}

    reservoir_node = wn.reservoir_name_list[0]
    pipe_freq = {pipe: 0.0 for pipe in wn.pipe_name_list}
    total_weight = 0.0

    for junction_name in wn.junction_name_list:
        Ij = float(node_importance.get(str(junction_name), 1.0))
        try:
            path = nx.shortest_path(G, source=junction_name, target=reservoir_node)
            total_weight += Ij
            for i in range(len(path) - 1):
                edge_data = G.get_edge_data(path[i], path[i + 1])
                if edge_data and "pipe_id" in edge_data:
                    pipe_freq[edge_data["pipe_id"]] += Ij
        except nx.NetworkXNoPath:
            continue

    if total_weight == 0:
        return {pipe: 0.0 for pipe in pipe_freq}
    return {pipe: (freq / total_weight) * 100 for pipe, freq in pipe_freq.items()}


# ============================================================
#  Enhanced Plotting Functions
# ============================================================

def plot_network_map(wn, link_values, title, output_path, cmap_name='coolwarm', 
                     label='Value (%)', show_legend=True, figsize=(12, 10), extra_text=None):
    """Enhanced plot with better styling - shows both pipes and nodes.

    extra_text: optional multiline string drawn inside the figure (e.g. to show
    composite weights or notes).
    """
    try:
        logging.info(f"Creating plot: {title}")
        
        # Get node coordinates
        node_coords = {}
        for node_name in wn.node_name_list:
            node = wn.get_node(node_name)
            coords = getattr(node, "coordinates", None)
            if coords:
                node_coords[node_name] = coords
        
        if len(node_coords) == 0:
            G = wn.get_graph()
            pos = nx.spring_layout(G, seed=42)
            for n, (x, y) in pos.items():
                node_coords[n] = (x * 1000, y * 1000)

        values = [v for v in link_values.values() if v is not None]
        if values:
            vmin, vmax = min(values), max(values)
        else:
            vmin, vmax = 0, 100
        
        # Use truncated colormap to avoid very light colors
        # This makes low values visible by starting from a darker color
        cmap_full = cm.get_cmap(cmap_name)
        if cmap_name in ['coolwarm', 'RdYlGn_r', 'Reds', 'Blues', 'Oranges', 'Greens', 
                         'YlOrRd', 'YlGnBu', 'YlOrBr', 'YlGn']:
            # For sequential colormaps, use only 40-100% of the range to avoid very light colors
            colors = cmap_full(np.linspace(0.4, 1.0, 256))
            cmap = mcolors.LinearSegmentedColormap.from_list('truncated', colors)
        else:
            cmap = cmap_full
        
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

        fig, ax = plt.subplots(figsize=figsize)
        
        # Plot pipes with varying thickness based on value
        for pipe_name in wn.pipe_name_list:
            pipe = wn.get_link(pipe_name)
            start_node = pipe.start_node_name
            end_node = pipe.end_node_name
            if start_node in node_coords and end_node in node_coords:
                x1, y1 = node_coords[start_node]
                x2, y2 = node_coords[end_node]
                val = link_values.get(pipe_name, 0)
                
                # Vary line width based on criticality (increased for better visibility)
                linewidth = 2 + (val / vmax) * 4 if vmax > 0 else 2
                ax.plot([x1, x2], [y1, y2], color=cmap(norm(val)), 
                       linewidth=linewidth, alpha=0.9, zorder=1)
                
                # Add pipe label at midpoint
                mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
                ax.text(mid_x, mid_y, pipe_name, fontsize=5, ha='center', va='center',
                       bbox=dict(boxstyle='round,pad=0.15', facecolor='white', 
                                edgecolor='none', alpha=0.7),
                       zorder=3)

        # Plot junction nodes with labels (highlight critical nodes)
        for node_name in wn.junction_name_list:
            if node_name in node_coords:
                x, y = node_coords[node_name]
                node_str = str(node_name)
                if node_str in CRITICAL_NODES:
                    # Critical node: use structure-specific marker and color
                    struct_name, _ = CRITICAL_NODES[node_str]
                    style = STRUCTURE_STYLES.get(struct_name, dict(marker='D', color='red'))
                    m = style['marker']
                    c = style['color']
                    label_text = f"{node_str}\n{struct_name}"
                    ax.plot(x, y, m, color=c, markersize=7, alpha=0.9,
                           markeredgecolor='black', markeredgewidth=0.8, zorder=3)
                    ax.text(x, y+40, label_text, fontsize=6, ha='center', va='bottom',
                           color=c, fontweight='bold',
                           bbox=dict(boxstyle='round,pad=0.2', facecolor='mistyrose', 
                                    edgecolor=c, alpha=0.9, linewidth=0.6),
                           zorder=5)
                else:
                    # Regular junction
                    ax.plot(x, y, 'o', color='gray', markersize=5, alpha=0.7,
                           markeredgecolor='black', markeredgewidth=0.5, zorder=2)
                    ax.text(x, y+30, node_name, fontsize=5, ha='center', va='bottom',
                           color='black', fontweight='normal',
                           bbox=dict(boxstyle='round,pad=0.15', facecolor='lightyellow', 
                                    edgecolor='gray', alpha=0.8, linewidth=0.3),
                           zorder=4)
        
        # Plot reservoirs with distinct styling and labels
        for res in wn.reservoir_name_list:
            if res in node_coords:
                x, y = node_coords[res]
                ax.plot(x, y, 's', color='blue', markersize=12, 
                       markeredgecolor='black', markeredgewidth=1.5,
                       label='Reservoir', zorder=10)
                # Add reservoir label
                ax.text(x, y+60, res, fontsize=7, ha='center', va='bottom',
                       color='blue', fontweight='bold',
                       bbox=dict(boxstyle='round,pad=0.25', facecolor='lightblue', 
                                edgecolor='blue', alpha=0.9, linewidth=1.0),
                       zorder=11)

        if show_legend:
            sm = cm.ScalarMappable(cmap=cmap, norm=norm)
            sm.set_array([])
            cbar = plt.colorbar(sm, ax=ax, label=label, shrink=0.8)
            cbar.ax.tick_params(labelsize=9)
            
            # Build legend for reservoirs and critical structures
            legend_handles = []
            if wn.reservoir_name_list:
                legend_handles.append(
                    Line2D([0], [0], marker='s', color='blue', linestyle='None',
                           markeredgecolor='black', markeredgewidth=1.0,
                           markersize=8, label='Reservoir')
                )

            # Unique structure names from CRITICAL_NODES, using STRUCTURE_STYLES
            structure_names = sorted({v[0] for v in CRITICAL_NODES.values()})
            for struct_name in structure_names:
                style = STRUCTURE_STYLES.get(struct_name, dict(marker='D', color='red'))
                legend_handles.append(
                    Line2D([0], [0], marker=style['marker'], color=style['color'], linestyle='None',
                           markeredgecolor='black', markeredgewidth=0.8,
                           markersize=7, label=struct_name)
                )

            if legend_handles:
                ax.legend(handles=legend_handles, loc='best', fontsize=9)
        
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.set_aspect("equal")
        ax.axis('off')

        # Optional extra text box (e.g., composite weights)
        if extra_text:
            ax.text(0.01, 0.01, extra_text,
                    transform=ax.transAxes,
                    fontsize=8,
                    va='bottom', ha='left',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                              edgecolor='gray', alpha=0.9, linewidth=0.5),
                    zorder=20)

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        logging.info(f"Saved: {output_path.name}")
    except Exception as e:
        logging.error(f"Error in plot_network_map: {str(e)}\n{traceback.format_exc()}")


def plot_node_resilience(wn, node_values, title, output_path, cmap_name='viridis'):
    """Plot network with nodes colored by their resilience contribution and pipes shown."""
    try:
        logging.info(f"Creating plot: {title}")
        
        node_coords = {}
        for node_name in wn.node_name_list:
            node = wn.get_node(node_name)
            coords = getattr(node, "coordinates", None)
            if coords:
                node_coords[node_name] = coords
        
        if len(node_coords) == 0:
            G = wn.get_graph()
            pos = nx.spring_layout(G, seed=42)
            for n, (x, y) in pos.items():
                node_coords[n] = (x * 1000, y * 1000)

        values = list(node_values.values())
        vmin, vmax = (min(values), max(values)) if values else (0, 1)
        cmap = cm.get_cmap(cmap_name)
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

        fig, ax = plt.subplots(figsize=(12, 10))
        
        # Plot ALL pipes with labels
        for pipe_name in wn.pipe_name_list:
            pipe = wn.get_link(pipe_name)
            start_node = pipe.start_node_name
            end_node = pipe.end_node_name
            if start_node in node_coords and end_node in node_coords:
                x1, y1 = node_coords[start_node]
                x2, y2 = node_coords[end_node]
                # Make pipes more visible with darker color and more opacity
                ax.plot([x1, x2], [y1, y2], color='gray', linewidth=2, alpha=0.7, zorder=1)
                
                # Add pipe label
                mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
                ax.text(mid_x, mid_y, pipe_name, fontsize=5, ha='center', va='center',
                       bbox=dict(boxstyle='round,pad=0.15', facecolor='white', 
                                edgecolor='none', alpha=0.7),
                       zorder=3)

        # Plot nodes with colors, varying sizes, and labels (highlight critical nodes)
        for node_name, val in node_values.items():
            if node_name in node_coords:
                x, y = node_coords[node_name]
                node_str = str(node_name)
                size = 60 + (val / vmax) * 200 if vmax > 0 else 60
                if node_str in CRITICAL_NODES:
                    struct_name, _ = CRITICAL_NODES[node_str]
                    style = STRUCTURE_STYLES.get(struct_name, dict(marker='D', color='red'))
                    c = style['color']
                    label_text = f"{node_str}\n{struct_name}"
                    ax.scatter(x, y, c=[cmap(norm(val))], s=size*1.2, 
                              edgecolors=c, linewidths=1.0, alpha=0.95, zorder=6)
                    ax.text(x, y+40, label_text, fontsize=6, ha='center', va='bottom',
                           color=c, fontweight='bold',
                           bbox=dict(boxstyle='round,pad=0.2', facecolor='mistyrose', 
                                    edgecolor=c, alpha=0.9, linewidth=0.6),
                           zorder=7)
                else:
                    ax.scatter(x, y, c=[cmap(norm(val))], s=size, 
                              edgecolors='black', linewidths=0.5, alpha=0.8, zorder=5)
                    ax.text(x, y+30, node_name, fontsize=5, ha='center', va='bottom',
                           color='black', fontweight='normal',
                           bbox=dict(boxstyle='round,pad=0.15', facecolor='white', 
                                    edgecolor='gray', alpha=0.8, linewidth=0.3),
                           zorder=6)

        # Plot reservoirs with distinct marker and labels
        for res in wn.reservoir_name_list:
            if res in node_coords:
                x, y = node_coords[res]
                ax.plot(x, y, 's', color='blue', markersize=12, 
                       markeredgecolor='black', markeredgewidth=1.5, 
                       label='Reservoir', zorder=10)
                # Add reservoir label
                ax.text(x, y+60, res, fontsize=7, ha='center', va='bottom',
                       color='blue', fontweight='bold',
                       bbox=dict(boxstyle='round,pad=0.25', facecolor='lightblue', 
                                edgecolor='blue', alpha=0.9, linewidth=1.0),
                       zorder=11)

        sm = cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax, label='Resilience Contribution', shrink=0.8)
        cbar.ax.tick_params(labelsize=9)
        
        # Add legend for reservoirs and critical structures
        legend_handles = []
        if wn.reservoir_name_list:
            legend_handles.append(
                Line2D([0], [0], marker='s', color='blue', linestyle='None',
                       markeredgecolor='black', markeredgewidth=1.0,
                       markersize=8, label='Reservoir')
            )

        structure_names = sorted({v[0] for v in CRITICAL_NODES.values()})
        for struct_name in structure_names:
            style = STRUCTURE_STYLES.get(struct_name, dict(marker='D', color='red'))
            legend_handles.append(
                Line2D([0], [0], marker=style['marker'], color=style['color'], linestyle='None',
                       markeredgecolor='black', markeredgewidth=0.8,
                       markersize=7, label=struct_name)
            )

        if legend_handles:
            ax.legend(handles=legend_handles, loc='best', fontsize=9)
        
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.set_aspect("equal")
        ax.axis('off')
        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        logging.info(f"Saved: {output_path.name}")
    except Exception as e:
        logging.error(f"Error in plot_node_resilience: {str(e)}\n{traceback.format_exc()}")


def create_criticality_comparison_plots(df, output_folder):
    """Create comparison plots for different criticality metrics."""
    try:
        logging.info("Creating comparison plots...")
        
        # 1. Correlation heatmap
        fig, ax = plt.subplots(figsize=(10, 8))
        metrics = ['Resilience_Reduction_%', 'Path_Frequency_%', 'Flow_Criticality_%',
                   'Betweenness_Centrality_%', 'Composite_Criticality']
        corr_matrix = df[metrics].corr()
        
        sns.heatmap(corr_matrix, annot=True, fmt='.3f', cmap='coolwarm', 
                   center=0, square=True, ax=ax, cbar_kws={'shrink': 0.8})
        ax.set_title('Criticality Metrics Correlation Matrix', fontsize=14, fontweight='bold', pad=20)
        plt.tight_layout()
        plt.savefig(output_folder / 'correlation_heatmap.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        # 2. Top 20 pipes comparison
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Top 20 Most Critical Pipes by Different Metrics', 
                    fontsize=16, fontweight='bold', y=1.00)
        
        metrics_plot = [
            ('Composite_Criticality', 'Composite Criticality Score', '#440154'),  # Dark purple
            ('Resilience_Reduction_%', 'Resilience Reduction (%)', '#d62728'),    # Red
            ('Path_Frequency_%', 'Path Frequency (%)', '#1f77b4'),                # Blue
            ('Betweenness_Centrality_%', 'Betweenness Centrality (%)', '#2ca02c') # Green
        ]
        
        for idx, (metric, title, color) in enumerate(metrics_plot):
            ax = axes[idx // 2, idx % 2]
            top_20 = df.nlargest(20, metric)
            
            bars = ax.barh(range(len(top_20)), top_20[metric], color=color)
            ax.set_yticks(range(len(top_20)))
            ax.set_yticklabels(top_20['Pipe_ID'], fontsize=8)
            ax.set_xlabel(title, fontsize=10, fontweight='bold')
            ax.set_title(f'Top 20 by {title}', fontsize=11, fontweight='bold')
            ax.invert_yaxis()
            ax.grid(axis='x', alpha=0.3)
            
            # Add value labels
            for i, (bar, val) in enumerate(zip(bars, top_20[metric])):
                ax.text(val, i, f' {val:.1f}', va='center', fontsize=7)
        
        plt.tight_layout()
        plt.savefig(output_folder / 'top_20_comparison.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        # 3. Distribution plots
        fig, axes = plt.subplots(2, 3, figsize=(18, 10))
        fig.suptitle('Distribution of Criticality Metrics', fontsize=16, fontweight='bold')
        
        metrics_dist = [
            ('Composite_Criticality', 'Composite Criticality'),
            ('Resilience_Reduction_%', 'Resilience Reduction (%)'),
            ('Path_Frequency_%', 'Path Frequency (%)'),
            ('Flow_Criticality_%', 'Flow Criticality (%)'),
            ('Betweenness_Centrality_%', 'Betweenness Centrality (%)'),
            ('Demand_Coverage_m3_s', 'Demand Coverage (m³/s)')
        ]
        
        for idx, (metric, title) in enumerate(metrics_dist):
            ax = axes[idx // 3, idx % 3]
            ax.hist(df[metric], bins=30, edgecolor='black', alpha=0.7)
            ax.set_xlabel(title, fontsize=10, fontweight='bold')
            ax.set_ylabel('Frequency', fontsize=10)
            ax.set_title(f'Distribution: {title}', fontsize=11)
            ax.grid(axis='y', alpha=0.3)
            
            # Add statistics
            mean_val = df[metric].mean()
            median_val = df[metric].median()
            ax.axvline(mean_val, color='r', linestyle='--', linewidth=2, label=f'Mean: {mean_val:.2f}')
            ax.axvline(median_val, color='g', linestyle='--', linewidth=2, label=f'Median: {median_val:.2f}')
            ax.legend(fontsize=8)
        
        plt.tight_layout()
        plt.savefig(output_folder / 'distributions.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        logging.info("Comparison plots created successfully")
        
    except Exception as e:
        logging.error(f"Error creating comparison plots: {str(e)}\n{traceback.format_exc()}")


# ============================================================
#  Main computation with enhanced metrics
# ============================================================

def compute_pipe_criticality(inp_file, min_head, output_folder, make_plots=True):
    logging.info("="*80)
    logging.info("PIPE CRITICALITY ANALYSIS STARTED")
    logging.info("="*80)
    
    logging.info("Loading network model...")
    wn = wntr.network.WaterNetworkModel(inp_file)
    
    # Build node-importance map (Ij) from user-defined critical nodes
    node_importance = get_node_importance(wn)
    
    # Network statistics
    n_junctions = len(wn.junction_name_list)
    n_pipes = len(wn.pipe_name_list)
    n_reservoirs = len(wn.reservoir_name_list)
    logging.info(f"Network Statistics:")
    logging.info(f"  - Junctions: {n_junctions}")
    logging.info(f"  - Pipes: {n_pipes}")
    logging.info(f"  - Reservoirs: {n_reservoirs}")

    logging.info("\nIdentifying critical components...")
    reservoir_pipes = identify_reservoir_pipes(wn)
    logging.info(f"  - Reservoir-connected pipes: {len(reservoir_pipes)}")

    logging.info("\nComputing path frequencies...")
    path_frequency = compute_path_frequency(wn, node_importance=node_importance)

    logging.info("\nRunning baseline simulation...")
    sim = wntr.sim.EpanetSimulator(wn)
    baseline_results = sim.run_sim()
    if baseline_results is None:
        raise ValueError("Baseline simulation failed")

    # Compute baseline resilience
    logging.info("\nComputing baseline resilience metrics...")
    baseline_X, baseline_nodes = compute_network_surplus(
        wn, baseline_results, min_head, node_importance=node_importance
    )
    reservoir_heads = [baseline_results.node['head'].loc[:, r].mean() 
                      for r in wn.reservoir_name_list]
    Hs = np.mean(reservoir_heads) if reservoir_heads else min_head
    denominator = sum(
        info['Qj'] * (Hs - min_head) * float(node_importance.get(str(node), 1.0))
        for node, info in baseline_nodes.items()
    )
    baseline_resilience = baseline_X / denominator if denominator > 1e-9 else 0.0
    
    logging.info(f"  - Network Weighted Surplus (X): {baseline_X:.6f}")
    logging.info(f"  - Resilience Index (Ir): {baseline_resilience:.6f}")

    # Plot baseline node resilience (already includes node importance via contributions)
    if make_plots and output_folder is not None:
        logging.info("\nGenerating baseline node resilience map...")
        node_values = {n: info["contribution"] for n, info in baseline_nodes.items()}
        plot_node_resilience(
            wn,
            node_values,
            "Baseline Node Resilience Contribution",
            output_folder / "01_node_resilience_baseline.png",
            cmap_name="viridis"
        )

    # Compute additional metrics
    logging.info("\nComputing additional criticality metrics...")
    baseline_flows = {pipe: abs(baseline_results.link['flowrate'].loc[:, pipe].mean())
                     for pipe in wn.pipe_name_list}

    # Pipe-importance factors based on endpoint node importance (average of Iu and Iv)
    pipe_importance = {}
    for pipe_name in wn.pipe_name_list:
        pipe = wn.get_link(pipe_name)
        Iu = float(node_importance.get(str(pipe.start_node_name), 1.0))
        Iv = float(node_importance.get(str(pipe.end_node_name), 1.0))
        pipe_importance[pipe_name] = 0.5 * (Iu + Iv)

    # Use importance-weighted flows to determine normalization
    weighted_flows = {
        pipe: baseline_flows.get(pipe, 0.0) * pipe_importance.get(pipe, 1.0)
        for pipe in wn.pipe_name_list
    }
    max_flow = max(weighted_flows.values()) if weighted_flows else 1.0
    
    logging.info("  - Computing betweenness centrality...")
    betweenness = compute_betweenness_centrality(wn, node_importance=node_importance)
    
    logging.info("  - Computing demand coverage...")
    total_network_demand = sum(
        abs(float(wn.get_node(j).base_demand or 0.0)) * float(node_importance.get(str(j), 1.0))
        for j in wn.junction_name_list
    )
    
    # Main analysis loop
    criticality_data = []
    total_pipes = len(wn.pipe_name_list)
    logging.info(f"\nAnalyzing {total_pipes} pipes for resilience impact...")
    
    for idx, pipe_name in enumerate(wn.pipe_name_list, 1):
        if idx % 20 == 0 or idx == total_pipes:
            logging.info(f"  Progress: {idx}/{total_pipes} pipes analyzed")

        # Get pipe properties
        pipe = wn.get_link(pipe_name)
        diameter = float(pipe.diameter)
        length = float(pipe.length)
        
        # 1. Resilience-based criticality
        if pipe_name in reservoir_pipes:
            delta_Ir = 100.0
        else:
            wn_temp = deepcopy(wn)
            wn_temp.get_link(pipe_name).initial_status = wntr.network.LinkStatus.Closed
            try:
                sim_temp = wntr.sim.EpanetSimulator(wn_temp)
                results_temp = sim_temp.run_sim()
                X_no_pipe, _ = compute_network_surplus(
                    wn_temp, results_temp, min_head, node_importance=node_importance
                )
                delta_Ir = ((baseline_X - X_no_pipe) / baseline_X) * 100 if baseline_X > 1e-9 else 0.0
                delta_Ir = max(0.0, min(delta_Ir, 100.0))
            except Exception as e:
                # Fallback: use importance-weighted flow share
                delta_Ir = (weighted_flows.get(pipe_name, 0.0) / max_flow) * 100

        # 2. Flow-based criticality (importance-weighted flows)
        flow_crit = compute_flow_based_criticality(
            baseline_flows, pipe_name, max_flow, pipe_importance=pipe_importance
        )
        
        # 3. Betweenness centrality (already importance-adjusted)
        bc = betweenness.get(pipe_name, 0.0)
        
        # 4. Path frequency (importance-weighted)
        pf = path_frequency.get(pipe_name, 0.0)
        
        # 5. Demand coverage (importance-weighted)
        demand_cov = compute_demand_coverage(wn, pipe_name, node_importance=node_importance)
        demand_cov_pct = (demand_cov / total_network_demand * 100) if total_network_demand > 0 else 0.0
        
        # 6. Segment importance (purely hydraulic/geometric)
        seg_importance = compute_segment_importance(wn, pipe_name, baseline_results)

        # Determine which types of critical nodes this pipe is directly connected to
        critical_types = []
        for node_endpoint in [pipe.start_node_name, pipe.end_node_name]:
            node_str = str(node_endpoint)
            if node_str in CRITICAL_NODES:
                struct_name, _ = CRITICAL_NODES[node_str]
                if struct_name not in critical_types:
                    critical_types.append(struct_name)
        is_critical_connected = ";".join(critical_types) if critical_types else "None"
        
        # Composite criticality (weighted average)
        w = COMPOSITE_WEIGHTS
        composite = (
            w['Resilience_Reduction_%']   * delta_Ir +
            w['Path_Frequency_%']         * pf +
            w['Flow_Criticality_%']       * flow_crit +
            w['Betweenness_Centrality_%'] * bc +
            w['Demand_Coverage_%']        * demand_cov_pct
        )
        
        # Classification
        if composite >= 75:
            criticality_class = "Critical"
        elif composite >= 50:
            criticality_class = "High"
        elif composite >= 25:
            criticality_class = "Medium"
        else:
            criticality_class = "Low"

        criticality_data.append({
            'Pipe_ID': pipe_name,
            'Diameter_m': round(diameter, 4),
            'Length_m': round(length, 2),
            'Resilience_Reduction_%': round(delta_Ir, 2),
            'Path_Frequency_%': round(pf, 2),
            'Flow_Criticality_%': round(flow_crit, 2),
            'Betweenness_Centrality_%': round(bc, 2),
            'Demand_Coverage_m3_s': round(demand_cov, 6),
            'Demand_Coverage_%': round(demand_cov_pct, 2),
            'Segment_Importance': round(seg_importance, 2),
            'Composite_Criticality': round(composite, 2),
            'Criticality_Class': criticality_class,
            'Is_Reservoir_Connected': pipe_name in reservoir_pipes,
            'Is_Critical_Connected': is_critical_connected
        })

    # Create DataFrame
    df = pd.DataFrame(criticality_data)
    df = df.sort_values(by='Composite_Criticality', ascending=False).reset_index(drop=True)
    df.insert(0, 'Rank', range(1, len(df) + 1))

    if make_plots and output_folder is not None:
        logging.info("\n" + "="*80)
        logging.info("GENERATING VISUALIZATIONS")
        logging.info("="*80)

        # Network maps for each metric
        metrics_to_plot = [
            ('Composite_Criticality', 'Composite Pipe Criticality Score', '02_network_composite_criticality.png', 'RdYlGn_r'),
            ('Resilience_Reduction_%', 'Resilience Reduction Impact (%)', '03_network_resilience_reduction.png', 'YlOrRd'),
            ('Path_Frequency_%', 'Path Frequency (%)', '04_network_path_frequency.png', 'YlGnBu'),
            ('Flow_Criticality_%', 'Flow-Based Criticality (%)', '05_network_flow_criticality.png', 'YlOrBr'),
            ('Betweenness_Centrality_%', 'Network Betweenness Centrality (%)', '06_network_betweenness.png', 'YlGn'),
        ]

        for metric, title, filename, cmap in metrics_to_plot:
            link_values = df.set_index('Pipe_ID')[metric].to_dict()

            # For resilience reduction, clip extreme high values at the 95th percentile
            # so that the color scale is not dominated by a few very high pipes and
            # differences among the rest become visually clearer.
            if metric == 'Resilience_Reduction_%' and link_values:
                vals = np.array(list(link_values.values()), dtype=float)
                high = np.percentile(vals, 95)
                for k in link_values.keys():
                    if link_values[k] > high:
                        link_values[k] = high

            # Build extra legend text for the composite criticality map
            extra_text = None
            if metric == 'Composite_Criticality':
                w = COMPOSITE_WEIGHTS
                extra_text = (
                    "Composite weights:\n"
                    f"- Resilience reduction: {w['Resilience_Reduction_%']:.2f}\n"
                    f"- Path frequency:      {w['Path_Frequency_%']:.2f}\n"
                    f"- Flow criticality:    {w['Flow_Criticality_%']:.2f}\n"
                    f"- Betweenness:         {w['Betweenness_Centrality_%']:.2f}\n"
                    f"- Demand coverage:     {w['Demand_Coverage_%']:.2f}"
                )

            plot_network_map(
                wn,
                link_values,
                title,
                output_folder / filename,
                cmap_name=cmap,
                label=metric.replace('_', ' '),
                extra_text=extra_text
            )

        # Create comparison plots
        create_criticality_comparison_plots(df, output_folder)

    logging.info("\n" + "="*80)
    logging.info("ANALYSIS COMPLETE")
    logging.info("="*80)

    return df, baseline_resilience, baseline_X, {
        "junctions": n_junctions,
        "pipes": n_pipes,
        "reservoirs": n_reservoirs,
        "reservoir_pipes": len(reservoir_pipes),
    }


def create_summary_report(df, baseline_resilience, baseline_X, output_folder, inp_file):
    """Create comprehensive summary report."""
    logging.info("\nGenerating summary statistics...")
    
    summary_stats = {
        'Metric': [],
        'Mean': [],
        'Median': [],
        'Std_Dev': [],
        'Min': [],
        'Max': [],
        'Q1': [],
        'Q3': []
    }
    
    metrics = ['Resilience_Reduction_%', 'Path_Frequency_%', 'Flow_Criticality_%',
               'Betweenness_Centrality_%', 'Composite_Criticality']
    
    for metric in metrics:
        summary_stats['Metric'].append(metric)
        summary_stats['Mean'].append(df[metric].mean())
        summary_stats['Median'].append(df[metric].median())
        summary_stats['Std_Dev'].append(df[metric].std())
        summary_stats['Min'].append(df[metric].min())
        summary_stats['Max'].append(df[metric].max())
        summary_stats['Q1'].append(df[metric].quantile(0.25))
        summary_stats['Q3'].append(df[metric].quantile(0.75))
    
    summary_df = pd.DataFrame(summary_stats)
    
    # Criticality class distribution
    class_dist = df['Criticality_Class'].value_counts().to_dict()
    
    # Create summary text file
    summary_file = output_folder / 'SUMMARY_REPORT.txt'
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("PIPE CRITICALITY ANALYSIS - SUMMARY REPORT\n")
        f.write("="*80 + "\n\n")
        f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Network File: {Path(inp_file).name}\n\n")
        
        f.write("-"*80 + "\n")
        f.write("BASELINE NETWORK METRICS\n")
        f.write("-"*80 + "\n")
        f.write(f"Network Weighted Surplus (X): {baseline_X:.6f}\n")
        f.write(f"Resilience Index (Ir): {baseline_resilience:.6f}\n")
        f.write(f"Total Pipes Analyzed: {len(df)}\n\n")
        
        f.write("-"*80 + "\n")
        f.write("CRITICALITY CLASS DISTRIBUTION\n")
        f.write("-"*80 + "\n")
        for cls in ['Critical', 'High', 'Medium', 'Low']:
            count = class_dist.get(cls, 0)
            pct = (count / len(df) * 100) if len(df) > 0 else 0
            f.write(f"{cls:12s}: {count:4d} pipes ({pct:5.1f}%)\n")
        
        f.write("\n" + "-"*80 + "\n")
        f.write("TOP 10 MOST CRITICAL PIPES (by Composite Score)\n")
        f.write("-"*80 + "\n")
        top_10 = df.head(10)[['Rank', 'Pipe_ID', 'Composite_Criticality', 
                              'Criticality_Class', 'Diameter_m', 'Length_m']]
        f.write(top_10.to_string(index=False))
        
        f.write("\n\n" + "-"*80 + "\n")
        f.write("STATISTICAL SUMMARY OF CRITICALITY METRICS\n")
        f.write("-"*80 + "\n")
        f.write(summary_df.to_string(index=False))
        
        f.write("\n\n" + "="*80 + "\n")
        f.write("METHODOLOGY\n")
        f.write("="*80 + "\n")
        f.write("""
This analysis evaluates pipe criticality using multiple metrics that are all
adjusted by node importance factors (Ij), where critical infrastructures such as
hospitals, schools, and fire departments are assigned Ij > 1 while other nodes
have Ij = 1 by default.

1. RESILIENCE REDUCTION (%): 
   - Measures impact on network surplus when a pipe is closed
   - Based on weighted surplus X = Sum(Ij * Cj * Qj * (Hj - Hl))
   - Nodes with higher importance factors contribute more to X
   - Higher values indicate more critical pipes

2. PATH FREQUENCY (%):
   - Importance-weighted percentage of shortest paths using each pipe
   - Each junction contributes its importance factor Ij to paths that
     originate from it, so pipes serving critical nodes appear more frequently

3. FLOW CRITICALITY (%):
   - Normalized importance-weighted flow rate through pipe
   - Flows in pipes connected to more important nodes receive larger weights

4. BETWEENNESS CENTRALITY (%):
   - Network topology-based metric, scaled by the average importance of the
     endpoint nodes of each pipe
   - Identifies pipes that strongly connect important parts of the network

5. COMPOSITE CRITICALITY:
   - Weighted combination of all metrics
   - Formula: 0.35*Resilience + 0.25*PathFreq + 0.20*Flow + 0.15*Betweenness + 0.05*Demand

CRITICALITY CLASSES:
   - Critical: Composite Score >= 75
   - High: Composite Score >= 50
   - Medium: Composite Score >= 25
   - Low: Composite Score < 25
        """)
    
    logging.info(f"Summary report saved: {summary_file.name}")
    return summary_df


def save_to_excel(df, summary_df, output_folder, filename='pipe_criticality_analysis.xlsx'):
    """Save results to Excel with multiple sheets."""
    try:
        logging.info(f"\nSaving results to Excel: {filename}")
        excel_path = output_folder / filename
        
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # Sheet 1: Complete results
            df.to_excel(writer, sheet_name='All_Pipes', index=False)
            
            # Sheet 2: Top 50 critical pipes
            df.head(50).to_excel(writer, sheet_name='Top_50_Critical', index=False)
            
            # Sheet 3: Critical class pipes only
            critical_pipes = df[df['Criticality_Class'] == 'Critical']
            critical_pipes.to_excel(writer, sheet_name='Critical_Pipes', index=False)
            
            # Sheet 4: High class pipes
            high_pipes = df[df['Criticality_Class'] == 'High']
            high_pipes.to_excel(writer, sheet_name='High_Criticality', index=False)
            
            # Sheet 5: Summary statistics
            summary_df.to_excel(writer, sheet_name='Statistics', index=False)
            
            # Sheet 6: Methodology
            methodology_text = pd.DataFrame({
                'Section': ['Overview', 'Metrics', 'Classification', 'Usage'],
                'Description': [
                    'This analysis evaluates water distribution network pipe criticality using multiple complementary metrics.',
                    '1. Resilience Reduction: Network surplus impact\n2. Path Frequency: Usage in shortest paths\n3. Flow Criticality: Normalized flow rates\n4. Betweenness: Network topology importance\n5. Composite: Weighted combination',
                    'Critical: ≥75, High: ≥50, Medium: ≥25, Low: <25',
                    'Use composite score for overall ranking. Examine individual metrics for specific insights.'
                ]
            })
            methodology_text.to_excel(writer, sheet_name='Methodology', index=False)
        
        logging.info(f"Excel file saved successfully: {excel_path.name}")
        
    except Exception as e:
        logging.error(f"Error saving to Excel: {str(e)}\n{traceback.format_exc()}")


# ============================================================
#  Main execution
# ============================================================

def main():
    # Input file path
    inp_file_path = r'C:\Users\Administrator\Desktop\Roya\Baghmalek\GA_Opt_WND_Bagh.inp'
    
    # Create output folder
    inp_path = Path(inp_file_path)
    file_basename = inp_path.stem
    output_folder = inp_path.parent / f"{file_basename}_Criticality_Results"
    output_folder.mkdir(exist_ok=True)
    
    # Setup logging
    setup_logging(output_folder)
    
    # Check file exists
    if not os.path.exists(inp_file_path):
        logging.error(f"INP file not found: {inp_file_path}")
        raise FileNotFoundError(f"INP file not found: {inp_file_path}")

    logging.info(f"Analyzing network: {inp_path.name}")
    logging.info(f"Output folder: {output_folder.name}")
    
    min_head = get_min_head()
    logging.info(f"Minimum head requirement: {min_head} m")

    # Run analysis
    df, baseline_resilience, baseline_X, _network_stats = compute_pipe_criticality(
        inp_file_path, min_head, output_folder, make_plots=True
    )

    # Create summary report
    summary_df = create_summary_report(
        df, baseline_resilience, baseline_X, output_folder, inp_file_path
    )

    # Save to Excel (single file with multiple sheets)
    # NOTE: Only ONE Excel file is created: pipe_criticality_analysis.xlsx
    save_to_excel(df, summary_df, output_folder)

    # # Save to CSV (complete data)
    # csv_path = output_folder / 'pipe_criticality_complete.csv'
    # df.to_csv(csv_path, index=False)
    # logging.info(f"\nCSV file saved: {csv_path.name}")
    
    # Clean up any duplicate Excel files from previous runs
    for old_file in output_folder.glob('pipe_criticality_combined.xlsx'):
        try:
            old_file.unlink()
            logging.info(f"Removed old file: {old_file.name}")
        except:
            pass

    logging.info("\n" + "="*80)
    logging.info("ALL OUTPUTS SAVED SUCCESSFULLY")
    logging.info("="*80)
    logging.info(f"\nResults location: {output_folder}")
    logging.info("\nGenerated files:")
    logging.info("  1. 01_node_resilience_baseline.png - Node resilience map")
    logging.info("  2. 02_network_composite_criticality.png - Composite criticality")
    logging.info("  3. 03_network_resilience_reduction.png - Resilience impact")
    logging.info("  4. 04_network_path_frequency.png - Path frequency")
    logging.info("  5. 05_network_flow_criticality.png - Flow criticality")
    logging.info("  6. 06_network_betweenness.png - Betweenness centrality")
    logging.info("  7. correlation_heatmap.png - Metrics correlation")
    logging.info("  8. top_20_comparison.png - Top pipes comparison")
    logging.info("  9. distributions.png - Statistical distributions")
    logging.info("  10. pipe_criticality_analysis.xlsx - Complete Excel report")
    logging.info("  11. pipe_criticality_complete.csv - Complete CSV data")
    logging.info("  12. SUMMARY_REPORT.txt - Text summary")
    logging.info("  13. analysis.log - Detailed log file")

    print("\n" + "="*80)
    print("ANALYSIS COMPLETE! Check the output folder for all results.")
    print("="*80)


def run_analysis(
    inp_file,
    min_head=None,
    critical_nodes=None,
    composite_weights=None,
    make_plots=False,
    output_folder=None,
):
    """API-friendly wrapper around the notebook criticality pipeline.

    Mutates module-level CRITICAL_NODES / COMPOSITE_WEIGHTS only for this call
    (same single-source-of-truth pattern as the notebook).
    """
    global CRITICAL_NODES, COMPOSITE_WEIGHTS

    saved_nodes = CRITICAL_NODES
    saved_weights = COMPOSITE_WEIGHTS
    try:
        if critical_nodes is not None:
            CRITICAL_NODES = {
                str(k): (str(v[0]), float(v[1])) for k, v in critical_nodes.items()
            }
        if composite_weights is not None:
            COMPOSITE_WEIGHTS = {str(k): float(v) for k, v in composite_weights.items()}

        if min_head is None:
            min_head = get_min_head()

        out = Path(output_folder) if output_folder else None
        if out is not None:
            out.mkdir(parents=True, exist_ok=True)
            setup_logging(out)

        df, baseline_resilience, baseline_X, network_stats = compute_pipe_criticality(
            inp_file, float(min_head), out, make_plots=make_plots
        )

        class_dist = df["Criticality_Class"].value_counts().to_dict()
        return {
            "network": network_stats,
            "baseline": {
                "weighted_surplus_X": float(baseline_X),
                "resilience_index_Ir": float(baseline_resilience),
                "min_head_m": float(min_head),
            },
            "composite_weights": dict(COMPOSITE_WEIGHTS),
            "critical_nodes": {
                k: {"structure": v[0], "importance": v[1]} for k, v in CRITICAL_NODES.items()
            },
            "class_distribution": {str(k): int(v) for k, v in class_dist.items()},
            "pipes": df.to_dict(orient="records"),
        }
    finally:
        CRITICAL_NODES = saved_nodes
        COMPOSITE_WEIGHTS = saved_weights


if __name__ == "__main__":
    main()